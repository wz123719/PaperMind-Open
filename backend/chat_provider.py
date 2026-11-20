"""Real provider SSE -> incremental NDJSON records. No simulated streaming."""
import asyncio
import codecs
import json
import time
import httpx
from .reading_provider import credential,ReadingFailure

REQUEST_SECONDS=120
MAX_BYTES=400000
MAX_TEXT=32000

class Records:
    def __init__(self,emit):
        self.buffer='';self.emit=emit;self.ended=False;self.count=0;self.text_size=0
    def feed(self,value):
        self.buffer+=value
        if len(self.buffer)>64000:raise ReadingFailure('流式记录超过64K字符上限')
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if line.strip():self.record(line)
    def record(self,line):
        if self.ended:raise ReadingFailure('模型结束记录后仍发送正文')
        try:
            data=json.loads(line)
            if not isinstance(data,dict):raise ValueError()
            kind=data.get('type')
            if kind=='text':
                if not isinstance(data.get('text'),str):raise ValueError()
                self.text_size+=len(data['text'])
                if self.text_size>MAX_TEXT:raise ReadingFailure('回答超过32000字符上限')
            elif kind=='claim':
                if not isinstance(data.get('claim'),dict):raise ValueError()
            elif kind=='end':self.ended=True
            else:raise ValueError()
            self.count+=1
            if self.count>600:raise ReadingFailure('流式记录超过600条上限')
            self.emit(data)
        except (ValueError,TypeError,KeyError) as exc:
            if isinstance(exc,ReadingFailure):raise
            raise ReadingFailure('模型流式正文协议不匹配，未发布完整回答') from None
    def finish(self):
        if self.buffer.strip():self.record(self.buffer)
        if not self.ended or not self.text_size:raise ReadingFailure('模型空流或缺少结束记录')

async def _stream(config,messages,emit,cancelled):
    key=credential(config);headers={'Content-Type':'application/json','Accept':'text/event-stream'}
    if key:headers['Authorization']='Bearer '+key
    records=Records(emit)
    async def pump():
        decoder=codecs.getincrementaldecoder('utf-8')('strict');buffer='';data=[];size=0;done=False
        def frame(lines):
            nonlocal done
            value='\n'.join(lines)
            if value=='[DONE]':done=True;return
            try:
                event=json.loads(value)
                if 'error' in event:raise ValueError()
                choice=event['choices'][0]
                if choice.get('finish_reason') in ('length','content_filter'):raise ValueError()
                text=choice.get('delta',{}).get('content')
                if text is not None:
                    if not isinstance(text,str):raise ValueError()
                    records.feed(text)
            except (ValueError,KeyError,IndexError,TypeError) as exc:
                if isinstance(exc,ReadingFailure):raise
                raise ReadingFailure('模型SSE帧无效或输出被截断') from None
        async with httpx.AsyncClient(timeout=httpx.Timeout(20,connect=10),follow_redirects=False,trust_env=False) as client:
            async with client.stream('POST',config['endpoint'],headers=headers,
                json={'model':config['model'],'messages':messages,'stream':True,'temperature':.2,'max_tokens':4000}) as response:
                if response.status_code!=200:raise ReadingFailure(f'模型服务HTTP {response.status_code}；响应正文未记录')
                if 'text/event-stream' not in response.headers.get('content-type',''):
                    raise ReadingFailure('模型服务不支持SSE流式协议，未改用伪流式')
                async for chunk in response.aiter_bytes():
                    size+=len(chunk)
                    if size>MAX_BYTES:raise ReadingFailure('模型流超过400KB上限')
                    try:buffer+=decoder.decode(chunk)
                    except UnicodeError:raise ReadingFailure('模型流UTF-8编码无效') from None
                    while '\n' in buffer:
                        line,buffer=buffer.split('\n',1);line=line.rstrip('\r')
                        if not line:
                            if data:frame(data);data=[]
                            if done:records.finish();return
                        elif line.startswith('data:'):data.append(line[5:].lstrip(' '))
                    if len(buffer)+sum(map(len,data))>64000:raise ReadingFailure('模型SSE帧超过64K上限')
                raise ReadingFailure('模型流中断，缺少[DONE]，草稿未完成')
    task=asyncio.create_task(pump());start=time.monotonic()
    try:
        while not task.done():
            if cancelled():raise ReadingFailure('问答租约失效，已取消模型请求')
            if time.monotonic()-start>REQUEST_SECONDS:raise ReadingFailure('问答请求超过120秒硬时限')
            await asyncio.wait({task},timeout=.2)
        return task.result()
    except httpx.HTTPError:
        raise ReadingFailure('模型流连接失败或超时；草稿未完成') from None
    finally:
        if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)

def stream(config,messages,emit,cancelled):
    return asyncio.run(_stream(config,messages,emit,cancelled))
