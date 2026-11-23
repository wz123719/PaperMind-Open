import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
import httpx
from sqlalchemy import select
from backend import reading, queue, parsing
from backend.db import engine, write_tx, jobs, reading_stages, reading_runs
from backend.files import LeaseLost
from backend.reading_provider import ReadingFailure, complete, validate_config
from backend.worker import execute as worker_execute
from test_parsing import uploaded, create, run

def ready(client):
    f=uploaded(client);p=create(client,f['file_id']);run(p)
    assert client.post('/v1/reading-settings',json={'endpoint':'http://127.0.0.1:9999/v1/chat/completions',
        'model':'protocol-test-only'}).status_code==200
    return p

def output(messages):
    source=json.loads(messages[-1]['content'])['source'][0]
    return json.dumps({'summary':'协议测试导览，非真实模型解读','claims':[{'text':'测试文本可追溯',
        'kind':'fact','verification':'supported','evidence':[{'block_id':source['block_id'],'quote':source['text'][:30]}]}]})

def provider(config,messages,cancelled):
    return output(messages)

def test_reading_full_workflow_reuses_and_binds_evidence(client):
    p=ready(client);r=reading.submit(p['id'])
    assert 'result' not in client.get('/v1/reading-runs/'+r['id']).json()
    assert client.get('/v1/reading-runs/'+r['id']+'/report').status_code==409
    assert reading.submit(p['id'],True)['id']==r['id']
    job=queue.claim('reader')
    reading.execute(job,'reader',lambda x:queue.progress(job['id'],'reader',x),lambda:False,provider)
    report=reading.report(r['id'])
    assert report['parse_run_id']==p['id']
    claim=report['sections'][0]['claims'][0]
    assert claim['verification']=='unreviewed'  # never trust model supported
    assert claim['evidence'][0]['matched'] and claim['evidence'][0]['regions']
    assert reading.submit(p['id'])['id']==r['id']
    assert reading.submit(p['id'],True)['id']!=r['id']

def test_first_run_uses_deepseek_without_storing_or_exposing_credentials(client,monkeypatch):
    from backend.reading_provider import credential
    defaults = client.get('/v1/reading-settings').json()
    assert defaults['configured'] and defaults['uses_default_model']
    assert defaults['endpoint'] == 'https://api.deepseek.com/chat/completions'
    assert defaults['model'] == 'deepseek-flash' and defaults['key_env'] == 'PAPERMIND_MODEL_API_KEY'
    assert defaults['revision'] is None
    monkeypatch.delenv('PAPERMIND_MODEL_API_KEY', raising=False)
    with pytest.raises(ReadingFailure, match='凭据环境变量未配置'):
        credential(defaults)
    monkeypatch.setenv('PAPERMIND_MODEL_API_KEY','fixture-secret-for-default')
    assert credential(defaults) == 'fixture-secret-for-default'
    assert 'fixture-secret-for-default' not in client.get('/v1/reading-settings').text
    assert 'fixture-secret-for-default' not in client.get('/v1/task-model-settings/translation').text


def test_config_invalid_and_credentials_never_in_api(client,monkeypatch):
    for url in ['http://remote.invalid/api','https://u:secret@example.com/api','https://example.com/api?key=secret','file:///etc/x']:
        assert client.post('/v1/reading-settings',json={'endpoint':url,'model':'test'}).status_code==409
    p=ready(client)
    monkeypatch.setenv('PAPERMIND_TEST_SECRET','secret-not-for-output')
    client.post('/v1/reading-settings',json={'endpoint':'https://example.com/chat','model':'test','key_env':'PAPERMIND_TEST_SECRET'})
    assert not client.get('/v1/reading-settings').json()['uses_default_model']
    r=client.post('/v1/parse-runs/'+p['id']+'/reading-runs',json={})
    assert r.status_code==202
    assert 'secret-not-for-output' not in r.text+client.get('/v1/reading-settings').text+client.get('/jobs/'+r.json()['job_id']).text
    monkeypatch.delenv('PAPERMIND_TEST_SECRET')
    assert client.post('/v1/parse-runs/'+p['id']+'/reading-runs',json={}).status_code==202

def test_heading_only_parent_does_not_block_child_reading(client, monkeypatch):
    parsed = ready(client)
    doc = parsing.structure(parsed['id'])
    paragraph = doc['blocks'][0]
    parent = {**paragraph, 'id': 'parent-heading', 'type': 'section_header',
              'text': '3. Preliminary', 'section_id': 'parent'}
    doc['blocks'] = [parent, {**paragraph, 'section_id': 'child'}]
    doc['sections'] = [{'id': 'parent', 'title': parent['text']},
                       {'id': 'child', 'title': '3.1. Method'}]
    monkeypatch.setattr(parsing, 'structure', lambda _: doc)
    run = reading.submit(parsed['id'])
    job = queue.claim('test-reader')

    def summarize(config, messages, cancelled):
        assert json.loads(messages[-1]['content'])['section'] == '3.1. Method'
        return output(messages)

    reading.execute(job, 'test-reader', lambda _: None, lambda: False, summarize)
    parent_result, child_result = reading.report(run['id'])['sections']
    assert parent_result['claims'] == []
    assert child_result['claims'][0]['evidence'][0]['matched']

def test_reading_unknown_and_incomplete_parse_rejected(client):
    assert client.get('/v1/reading-runs/missing').status_code==404
    assert client.post('/v1/parse-runs/missing/reading-runs',json={}).status_code==404
    f=uploaded(client);p=create(client,f['file_id'])
    assert client.post('/v1/parse-runs/'+p['id']+'/reading-runs',json={}).status_code==409

@pytest.mark.parametrize('bad',[None,'not json','{}','{"summary":"x","claims":[]}'])
def test_invalid_model_output_not_published(bad):
    with pytest.raises(ReadingFailure):reading.validate_output(bad,{},[],'current')

@pytest.mark.parametrize('case',['unknown','wrong_quote','no_region','other_section','inferred','conflicted','unsupported'])
def test_evidence_is_conservative(case):
    block={'parse_run_id':'current','text':'a sufficiently long original sentence','regions':[{'page_index':0,'bbox':[0,0,1,1]}],'quality_flags':['native_only']}
    claim={'text':'a claim','kind':'fact','verification':'supported','evidence':[{'block_id':'current:b1','quote':block['text']}]}
    allowed=[{'block_id':'current:b1','parse_run_id':'current','start':0,'end':len(block['text']),'text':block['text'],'fragment_id':'test-fragment'}]
    if case=='unknown':claim['evidence'][0]['block_id']='other:b1'
    if case=='wrong_quote':claim['evidence'][0]['quote']='invented quotation'
    if case=='no_region':block['regions']=[]
    if case=='other_section':allowed=[]
    if case=='inferred':claim['kind']='inference'
    if case in ('conflicted','unsupported'):claim['verification']=case
    result=reading.validate_output(json.dumps({'summary':'topic','claims':[claim]}),{'current:b1':block},allowed,'current')['claims'][0]
    assert result['verification']==('inferred' if case=='inferred' else 'conflicted' if case=='conflicted' else 'unsupported')

def test_chunking_preserves_long_block_and_rejects_oversize():
    text='abcdefghij'*3000
    doc={'sections':[],'blocks':[{'id':'b1','section_id':None,'text':text,'quality_flags':[]}]}
    stages=reading.plan(doc)
    assert ''.join(x['text'] for s in stages for x in s['source'])==text
    assert all(sum(len(json.dumps(x,ensure_ascii=False)) for x in s['source'])<=reading.MAX_CHARS for s in stages)
    with pytest.raises(ReadingFailure):reading.plan({'sections':[],'blocks':[]})
    doc['blocks'][0]['text']='a'*(reading.MAX_CHARS*101)
    with pytest.raises(ReadingFailure,match='100'):reading.plan(doc)

def test_config_changes_and_concurrent_duplicates_isolate(client):
    p=ready(client)
    with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:reading.submit(p['id']),range(8)))
    assert len({r['id'] for r in results})==1
    reading.configure({'endpoint':'http://localhost:9999/api','model':'different'})
    changed=reading.submit(p['id'])
    assert changed['input_hash']!=results[0]['input_hash']

def test_lease_loss_no_checkpoint_no_publish_and_recovery(client):
    p=ready(client);r=reading.submit(p['id']);job=queue.claim('stale')
    def expire(config,messages,cancelled):
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(lease_expires_at=0))
        return output(messages)
    with pytest.raises(LeaseLost):reading.execute(job,'stale',lambda _:None,lambda:False,expire)
    with engine.connect() as c:assert not c.execute(select(reading_stages)).all()
    assert client.get('/v1/reading-runs/'+r['id']+'/report').status_code==409
    recovered=queue.claim('new')
    reading.execute(recovered,'new',lambda _:None,lambda:False,provider)
    assert reading.report(r['id'])['run']['attempts']==2

def test_failed_stage_retry_reuses_checkpoint_old_report_unchanged(client,monkeypatch):
    p=ready(client);old=reading.submit(p['id']);job=queue.claim('reader')
    reading.execute(job,'reader',lambda _:None,lambda:False,provider)
    before=reading.report(old['id'])
    r=reading.submit(p['id'],True);job=queue.claim('reader')
    original=reading.plan
    def twice(doc):
        one=original(doc)[0];return [one,{**one,'key':'second'}]
    monkeypatch.setattr(reading,'plan',twice)
    calls=[]
    def broken(config,messages,cancelled):
        calls.append(1)
        if len(calls)==2:raise ReadingFailure('controlled failure')
        return output(messages)
    with pytest.raises(ReadingFailure):reading.execute(job,'reader',lambda _:None,lambda:False,broken)
    queue.finish(job['id'],'reader',error='controlled failure')
    assert client.get('/v1/reading-runs/'+r['id']+'/report').status_code==409
    assert reading.report(old['id'])==before
    with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(available_at=0))
    recovered=queue.claim('reader2');calls.clear()
    def count(config,messages,cancelled):calls.append(1);return output(messages)
    reading.execute(recovered,'reader2',lambda _:None,lambda:False,count)
    assert len(calls)==1 and len(reading.report(r['id'])['sections'])==2

def test_worker_reading_failures_have_bounded_retries_and_redacted_logs(client,monkeypatch,caplog):
    p=ready(client);r=reading.submit(p['id'])
    def bad(*args,**kwargs):raise RuntimeError('Authorization: secret-leak-attempt')
    monkeypatch.setattr(reading,'execute',bad)
    for attempt in range(3):
        job=queue.claim('reader');worker_execute(job,'reader')
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(available_at=0))
    assert reading.get_run(r['id'])['status']=='failed'
    assert not queue.claim('reader')
    assert 'secret-leak-attempt' not in caplog.text+json.dumps(queue.get_job(job['id']))

def test_transport_wire_protocol_and_error_redaction(monkeypatch):
    from backend import reading_provider as transport
    real=httpx.AsyncClient
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
    monkeypatch.setattr(transport.httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(respond)))
    monkeypatch.setenv('PAPERMIND_WIRE_KEY','not-public')
    config=validate_config({'endpoint':'https://example.com/chat','model':'wire-test','key_env':'PAPERMIND_WIRE_KEY'})
    assert complete(config,[{'role':'user','content':'fixture'}],lambda:False)=='{"ok":true}'
    assert seen[0].headers['authorization']=='Bearer not-public'
    body=json.loads(seen[0].content);assert body['stream'] is False and body['max_tokens']==3000 and 'tools' not in body
    def denied(request):return httpx.Response(401,text='secret-provider-body')
    monkeypatch.setattr(transport.httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(denied)))
    with pytest.raises(ReadingFailure,match='HTTP 401') as exc:complete(config,[],lambda:False)
    assert 'secret-provider-body' not in str(exc.value)

def test_transport_cancel_aborts_pending_request(monkeypatch):
    import asyncio
    from backend import reading_provider as transport
    real=httpx.AsyncClient
    async def stalled(request):await asyncio.sleep(5);return httpx.Response(200)
    monkeypatch.setattr(transport.httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(stalled)))
    start=time.monotonic()
    with pytest.raises(ReadingFailure,match='租约'):complete({'endpoint':'http://localhost/test','model':'test'},[],lambda:True)
    assert time.monotonic()-start<1

def test_transport_hard_deadline_and_response_limit(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from backend import reading_provider as transport
    real=httpx.AsyncClient
    async def stalled(request):await asyncio.sleep(5);return httpx.Response(200)
    monkeypatch.setattr(transport.httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(stalled)))
    clock=iter([0,91])
    with monkeypatch.context() as m:
        m.setattr(transport,'time',SimpleNamespace(monotonic=lambda:next(clock)))
        with pytest.raises(ReadingFailure,match='90秒'):complete({'endpoint':'http://localhost/test','model':'test'},[],lambda:False)
    monkeypatch.setattr(transport.httpx,'AsyncClient',lambda **kw:real(**kw,transport=httpx.MockTransport(lambda _:httpx.Response(200,content=b'x'*400001))))
    with pytest.raises(ReadingFailure,match='400KB'):complete({'endpoint':'http://localhost/test','model':'test'},[],lambda:False)

def test_total_budget_stops_stage_before_publish(client,monkeypatch):
    from types import SimpleNamespace
    p=ready(client);r=reading.submit(p['id']);job=queue.claim('reader')
    elapsed=[0]
    monkeypatch.setattr(reading,'time',SimpleNamespace(monotonic=lambda:elapsed[0],time=time.time))
    def expired(config,messages,cancelled):elapsed[0]=1201;return output(messages)
    with pytest.raises(ReadingFailure,match='1200'):reading.execute(job,'reader',lambda _:None,lambda:False,expired)
    assert client.get('/v1/reading-runs/'+r['id']+'/report').status_code==409
    with engine.connect() as c:assert not c.execute(select(reading_stages)).all()
