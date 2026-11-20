import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from backend import chat,chat_sources,queue,parsing
from backend.db import engine,write_tx,jobs,chat_messages,chat_events
from backend.files import LeaseLost
from backend.reading_provider import ReadingFailure
from test_reading import ready

def selection_for(p):
    doc=parsing.structure(p['id']);b=doc['blocks'][0]
    return {'parse_run_id':p['id'],'paper_file_id':p['paper_file_id'],'file_sha256':p['file_sha256'],
        'page_index':0,'text':b['text'],'layer_text':b['text'],'layer_start':0,'layer_end':len(b['text'])}

def choose(p):
    selected=selection_for(p);mapped=chat_sources.map_selection(p['id'],selected)
    return {**selected,'candidate_id':mapped['candidates'][0]['candidate_id']}

def fake(config,messages,emit,cancelled):
    source=json.loads(messages[-1]['content'])['source']
    emit({'type':'text','text':'协议测试正文😀'} )
    emit({'type':'claim','claim':{'text':'protocol fixture fact','kind':'fact','verification':'supported',
        'evidence':[{'block_id':source[0]['block_id'],'quote':source[0]['text'][:25]}] if source else []}})
    emit({'type':'end'})

def run_turn(turn,provider=fake,worker='chat-worker'):
    job=queue.claim(worker);assert job['id']==turn['job_id']
    chat.execute(job,worker,lambda:False,provider);return chat.turn(turn['id'])

def test_three_rounds_selection_history_removal_retrieval_and_evidence(client):
    p=ready(client);selected=choose(p);session=chat.create_session(p['id'])
    one=chat.submit(session['id'],'解释所选原文','turn-key-0001',selected)
    def inspect(config,messages,emit,cancelled):
        source=json.loads(messages[-1]['content'])['source'];emit({'type':'text','text':'early body'})
        assert chat.messages(session['id'])[-1]['status']=='draft'
        assert chat.events(one['id'])[-1]['type']=='delta'
        assert chat.turn(one['id'])['status']=='running'
        emit({'type':'claim','claim':{'text':'fact','kind':'fact','verification':'supported',
            'evidence':[{'block_id':source[0]['block_id'],'quote':source[0]['text'][:25]}]}})
    run_turn(one,inspect)
    two=chat.submit(session['id'],'继续解释','turn-key-0002',selected);run_turn(two)
    three=chat.submit(session['id'],'upload verification','turn-key-0003');run_turn(three)
    assert len(three['snapshot']['history'])==4
    assert three['snapshot']['selection'] is None and three['snapshot']['retrieval']['hits']>0
    assert one['snapshot']['selection']['source']==two['snapshot']['selection']['source']
    final=chat.messages(session['id'])[-1]
    assert final['status']=='completed' and final['data']['claims'][0]['verification']=='unreviewed'
    assert final['data']['claims'][0]['evidence'][0]['source_fragments']
    assert len(chat.messages(session['id']))==6

def test_selection_revalidated_not_client_source_or_regions(client):
    p=ready(client);chosen=choose(p);chosen['source']=[{'text':'FORGED'}];chosen['client_regions']=[{'bbox':[0,0,0,0]}]
    sid=chat.create_session(p['id'])['id'];turn=chat.submit(sid,'question','key-selection',chosen)
    assert all(s['text']!='FORGED' for s in turn['snapshot']['source'])
    assert turn['snapshot']['selection']['regions'][0]['bbox']!=[0,0,0,0]
    chosen['candidate_id']='forged'
    with pytest.raises(ReadingFailure):chat.submit(sid,'question','other-key',chosen)

@pytest.mark.parametrize('case',['page','file','run','sha','text','utf16'])
def test_wrong_selection_identity_and_text(client,case):
    p=ready(client);selected=selection_for(p)
    if case=='page':selected['page_index']=1
    if case=='file':selected['paper_file_id']='other'
    if case=='run':selected['parse_run_id']='other'
    if case=='sha':selected['file_sha256']='0'*64
    if case=='text':selected.update(text='forged sentence',layer_text='forged sentence',layer_end=15)
    if case=='utf16':selected['layer_end']+=1
    if case in ('page','text'):assert chat_sources.map_selection(p['id'],selected)['status']=='unmatched'
    else:
        with pytest.raises(ReadingFailure):chat_sources.map_selection(p['id'],selected)

def test_unicode_normalization_ambiguity_multiple_blocks_and_regions(monkeypatch):
    b1={'id':'r:b1','parse_run_id':'r','text':'中文😀e\u0301 hyphen-\nated value','regions':[{'page_index':0,'bbox':[0,0,1,.5]},{'page_index':1,'bbox':[0,0,1,.5]}],'data':{},'quality_flags':[]}
    b2={**b1,'id':'r:b2','text':' second block ending'}
    doc={'run':{'id':'r','paper_file_id':'f','file_sha256':'sha','pages':[{},{}]},'sections':[],'blocks':[b1,b2]}
    monkeypatch.setattr(chat_sources.parsing,'structure',lambda _:doc)
    monkeypatch.setattr(chat_sources,'page_text_matches',lambda *args:True)
    def sel(text):return {'parse_run_id':'r','paper_file_id':'f','file_sha256':'sha','page_index':0,'text':text,'layer_text':text,'layer_start':0,'layer_end':len(text)}
    mapped=chat_sources.map_selection('r',sel('中文😀é hyphen-ated value second block'))
    assert mapped['status']=='matched' and len(mapped['candidates'][0]['source'])==2
    assert len(mapped['candidates'][0]['regions'])==4
    assert mapped['candidates'][0]['source'][0]['text']==b1['text']
    b2['text']='中文😀é hyphen-ated value'
    assert chat_sources.map_selection('r',sel('hyphen-ated value'))['status']=='ambiguous'

def test_idempotency_session_serialization_and_cross_session_isolation(client):
    p=ready(client);a=chat.create_session(p['id']);b=chat.create_session(p['id'])
    with ThreadPoolExecutor(4) as pool:turns=list(pool.map(lambda _:chat.submit(a['id'],'upload','same-key-000'),range(6)))
    assert len({x['id'] for x in turns})==1
    with pytest.raises(ReadingFailure,match='幂等'):chat.submit(a['id'],'different','same-key-000')
    with pytest.raises(ReadingFailure,match='已有生成'):chat.submit(a['id'],'another','new-key-000')
    other=chat.submit(b['id'],'upload','other-key-000')
    assert other['snapshot']['history']==[] and other['snapshot']['identity']['id']==b['id']

def test_retry_replaces_draft_event_replay_and_stale_worker_denied(client):
    p=ready(client);sid=chat.create_session(p['id'])['id'];turn=chat.submit(sid,'upload','retry-key-000')
    job=queue.claim('old')
    def broken(config,messages,emit,cancelled):emit({'type':'text','text':'BROKEN_DRAFT'});raise ReadingFailure('controlled break')
    with pytest.raises(ReadingFailure):chat.execute(job,'old',lambda:False,broken)
    queue.finish(job['id'],'old',error='controlled break')
    assert chat.messages(sid)[-1]['status']=='draft'
    with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(available_at=0))
    recovered=queue.claim('new');chat.execute(recovered,'new',lambda:False,fake)
    assert chat.messages(sid)[-1]['content']=='协议测试正文😀'
    all_events=chat.events(turn['id']);starts=[e for e in all_events if e['type']=='start']
    assert [e['attempt'] for e in starts]==[1,2]
    cursor=all_events[2]['id'];assert all(e['id']>cursor for e in chat.events(turn['id'],cursor))
    with pytest.raises(LeaseLost):chat.execute(job,'old',lambda:False,fake)
    assert chat.messages(sid)[-1]['content']=='协议测试正文😀'

def test_lease_expiration_recovery_and_finite_failure_preserves_success(client):
    p=ready(client);sid=chat.create_session(p['id'])['id'];old=chat.submit(sid,'upload','old-key-000');run_turn(old)
    before=chat.messages(sid)[-1]
    new=chat.submit(sid,'upload again','fail-key-000')
    for i in range(3):
        job=queue.claim('dying')
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(lease_expires_at=0))
    assert queue.claim('exhausted') is None
    assert chat.turn(new['id'])['status']=='failed'
    assert chat.messages(sid)[-1]['status']=='failed' and chat.messages(sid)[1]==before
    assert chat.events(new['id'])[-1]['data']['terminal'] is True
    queue.retry(new['job_id'])
    assert chat.turn(new['id'])['max_attempts']==6

def test_snapshot_config_frozen_and_no_hit_uncited_advice(client):
    from backend import reading
    p=ready(client);sid=chat.create_session(p['id'])['id'];turn=chat.submit(sid,'zzzznotpresent','config-key-000')
    old=turn['snapshot']['config'];reading.configure({'endpoint':'http://localhost/new','model':'new'})
    assert chat.turn(turn['id'])['snapshot']['config']==old
    assert turn['snapshot']['retrieval']['status']=='no_hits' and turn['snapshot']['source']==[]
    def advice(config,messages,emit,cancelled):
        assert config==old;emit({'type':'text','text':'这是工程建议，未发现原文依据'})
        emit({'type':'claim','claim':{'text':'engineering suggestion','kind':'advice','verification':'supported','evidence':[]}})
    run_turn(turn,advice)
    claim=chat.messages(sid)[-1]['data']['claims'][0]
    assert claim['kind']=='advice' and claim['verification']=='unsupported'

def test_chat_api_status_events_and_bounds(client):
    p=ready(client)
    sid=client.post('/v1/chat-sessions',json={'parse_run_id':p['id']}).json()['id']
    assert client.get('/v1/chat-sessions/'+sid).status_code==200
    response=client.post('/v1/chat-sessions/'+sid+'/messages',json={'question':'upload','idempotency_key':'http-key-000'})
    assert response.status_code==202;turn=response.json();run_turn(turn)
    stream=client.get('/v1/chat-turns/'+turn['id']+'/events')
    assert 'event: delta' in stream.text and 'event: completed' in stream.text
    final_id=chat.events(turn['id'])[-1]['id']
    assert client.get('/v1/chat-turns/'+turn['id']+'/events',headers={'Last-Event-ID':str(final_id)}).text==''
    assert client.get('/v1/chat-turns/'+turn['id']+'/events',headers={'Last-Event-ID':'wrong'}).status_code==400
    with pytest.raises(ReadingFailure):chat.submit(sid,' '*4000+'x','big-key-000')
    assert client.get('/v1/chat-turns/missing').status_code==404

def test_saved_selection_reuse_is_explicit_and_session_bound(client):
    p=ready(client);a=chat.create_session(p['id'])['id'];b=chat.create_session(p['id'])['id']
    first=chat.submit(a,'first','reuse-first-key',choose(p));run_turn(first)
    reused=chat.submit(a,'continue','reuse-next-key',reuse_selection_turn_id=first['id'])
    assert reused['snapshot']['selection']['origin']=='saved_turn'
    assert reused['snapshot']['selection']['source']==first['snapshot']['selection']['source']
    with pytest.raises(ReadingFailure,match='其他会话'):chat.submit(b,'cross','reuse-cross-key',reuse_selection_turn_id=first['id'])
    with pytest.raises(ReadingFailure,match='同时'):chat.submit(b,'both','reuse-both-key',choose(p),first['id'])

def test_multi_page_block_cannot_authorize_text_on_wrong_native_page(client):
    from backend.db import document_blocks
    p=ready(client);doc=parsing.structure(p['id']);block=doc['blocks'][0]
    regions=block['regions']+[{**block['regions'][0],'page_index':1}]
    with write_tx() as c:c.execute(document_blocks.update().where(document_blocks.c.id==block['id']).values(regions=regions))
    selected=selection_for(p);selected['page_index']=1
    result=chat_sources.map_selection(p['id'],selected)
    assert result['status']=='unmatched' and not result['candidates']
    assert 'PDF页' in result['reason']
