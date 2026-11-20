import asyncio
import json
import time
import httpx
import pytest
from backend import chat_provider as provider
from backend.reading_provider import ReadingFailure

class Chunks(httpx.AsyncByteStream):
    def __init__(self,raw):self.raw=raw
    async def __aiter__(self):
        for i in range(0,len(self.raw),3):await asyncio.sleep(0);yield self.raw[i:i+3]

def frames(content,done=True):
    raw=b''
    for text in content:
        raw+=('data: '+json.dumps({'choices':[{'delta':{'content':text}}]},ensure_ascii=False)+'\r\n\r\n').encode()
    return raw+(b'data: [DONE]\r\n\r\n' if done else b'')

def configure(monkeypatch,raw,status=200,content_type='text/event-stream'):
    real=httpx.AsyncClient
    def respond(request):
        assert json.loads(request.content)['stream'] is True
        return httpx.Response(status,headers={'Content-Type':content_type},stream=Chunks(raw))
    monkeypatch.setattr(provider.httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(respond)))

def test_utf8_network_fragmentation_and_incremental_visible_records(monkeypatch):
    line=json.dumps({'type':'text','text':'测试😀é'},ensure_ascii=False)+'\n'
    end='{"type":"end"}\n'
    configure(monkeypatch,frames([line[:12],line[12:],end]))
    seen=[];provider.stream({'endpoint':'http://localhost/model','model':'test'},[],seen.append,lambda:False)
    assert seen==[{'type':'text','text':'测试😀é'},{'type':'end'}]

@pytest.mark.parametrize('case',['no_done','empty','invalid_json','invalid_utf8','no_end','wrong_type','http_error','content_type','length'])
def test_stream_failures_never_promote_partial_output(monkeypatch,case):
    content=['{"type":"text","text":"draft"}\n','{"type":"end"}\n'];raw=frames(content)
    status=200;ctype='text/event-stream'
    if case=='no_done':raw=frames(content,False)
    if case=='empty':raw=frames([])
    if case=='invalid_json':raw=b'data: nope\n\n'
    if case=='invalid_utf8':raw=b'data: \xff\n\n'
    if case=='no_end':raw=frames(content[:1])
    if case=='wrong_type':raw=frames(['{"type":"evil"}\n'])
    if case=='http_error':status=401;raw=b'SECRET_BODY_MUST_NOT_APPEAR'
    if case=='content_type':ctype='application/json'
    if case=='length':raw=b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
    configure(monkeypatch,raw,status,ctype)
    with pytest.raises(ReadingFailure) as exc:provider.stream({'endpoint':'http://localhost/model','model':'test'},[],lambda _:None,lambda:False)
    assert 'SECRET_BODY_MUST_NOT_APPEAR' not in str(exc.value)

def test_output_limit_and_idle_hard_timeout(monkeypatch):
    configure(monkeypatch,frames(['{"type":"text","text":"'+('x'*32001)+'"}\n']))
    with pytest.raises(ReadingFailure):provider.stream({'endpoint':'http://localhost/model','model':'test'},[],lambda _:None,lambda:False)
    monkeypatch.undo();real=httpx.AsyncClient
    async def stalled(request):await asyncio.sleep(5);return httpx.Response(200)
    monkeypatch.setattr(provider.httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(stalled)))
    monkeypatch.setattr(provider,'REQUEST_SECONDS',.01)
    start=time.monotonic()
    with pytest.raises(ReadingFailure,match='硬时限'):provider.stream({'endpoint':'http://localhost/model','model':'test'},[],lambda _:None,lambda:False)
    assert time.monotonic()-start<1
