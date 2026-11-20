import json
import re
import time
import pytest
from sqlalchemy import select
from backend import translation as t, queue, reading
from backend.db import engine,write_tx,jobs,translation_batches,translation_blocks
from backend.files import LeaseLost
from backend.translation_protection import protect,restore,TOKEN
from backend.reading_provider import ReadingFailure
from test_parsing import uploaded,create,run


def ready(client):
    file=uploaded(client);parse=create(client,file['file_id']);run(parse)
    t.configure('translation',{'endpoint':'http://127.0.0.1:9999/chat/completions','model':'TEST ONLY'})
    return parse,file


def provider(config,messages,cancelled):
    data=json.loads(messages[-1]['content'])
    return json.dumps({'blocks':[{'source_block_id':b['source_block_id'],'text':'测试协议译文 '+''.join(TOKEN.findall(b['text']))} for b in reversed(data['targets'])]}),None


def test_workspace_model_default_and_task_override(client):
    file = uploaded(client)
    parse = create(client, file['file_id'])
    run(parse)
    endpoint = 'http://127.0.0.1:9999/chat/completions'
    shared = reading.configure({'endpoint': endpoint, 'model': 'shared', 'key_env': 'MODEL_TEST_KEY'})
    for task in ('translation', 'glossary'):
        configuration = client.get(f'/v1/task-model-settings/{task}').json()
        assert configuration['source'] == 'workspace' and configuration['revision'] is None
        job = t.submit(parse['id'], 'full', [], f'shared-{task}', task=task)
        assert job['snapshot']['config']['model'] == 'shared'
        assert job['snapshot']['config']['settings_revision'] == shared['revision']
        assert job['snapshot']['config']['key_env'] == 'MODEL_TEST_KEY'
    override = client.post('/v1/task-model-settings/translation', json={
        'endpoint': endpoint, 'model': 'dedicated', 'expected_revision': None,
    })
    assert override.status_code == 200
    job = t.submit(parse['id'], 'full', [], 'dedicated-translation')
    assert job['snapshot']['config']['model'] == 'dedicated'
    assert t.settings('glossary')['model'] == 'shared'


@pytest.mark.parametrize('text',[
    'The result is -2.3e-5 ms and −4 × 10^-7, [12–14], Figure 2.',
    'Given $x_{i}^{-2} < y$ and $$\na+b > c\n$$ in `x=1`.',
    'Use 10⁻³ and α ≤ β with neural network, emoji 🧪.',
    'Literal ⟦PM:original:0⟧ remains with 98.5%.',
])
def test_exact_protection(text):
    protected,mapping=protect(text,[{'english':'neural network','chinese':'神经网络'}])
    restored=restore(text,protected,'中文翻译 '+''.join(TOKEN.findall(protected)),mapping)
    assert all(value in restored for value in mapping.values())
    for broken in ['',protected+'⟦PM:foreign:0⟧','中文'+''.join(TOKEN.findall(protected))*2]:
        with pytest.raises(ValueError):restore(text,protected,broken,mapping)


@pytest.mark.parametrize('mode',['missing','duplicate','unknown','cross_run','token','number','unchanged'])
def test_reject_bad_response(mode):
    text='The method uses neural network with 5 layers.'
    protected,mapping=protect(text,[{'english':'neural network','chinese':'神经网络'}])
    targets=[{'id':'run-A/block','text':text,'protected':protected,'mapping':mapping}]
    row={'source_block_id':'run-A/block','text':'该方法采用 '+''.join(TOKEN.findall(protected))}
    rows=[row]
    if mode=='missing':rows=[]
    if mode=='duplicate':rows=[row,row]
    if mode=='unknown':row['source_block_id']='other'
    if mode=='cross_run':row['source_block_id']='run-B/block'
    if mode=='token':row['text']='该方法采用错误术语'
    if mode=='number':row['text']+=' 99'
    if mode=='unchanged':row['text']=protected
    with pytest.raises(ReadingFailure):t.validate_response(json.dumps({'blocks':rows}),targets)


def test_reverse_alignment_and_longest_term():
    terms=[{'english':'neural network','chinese':'神经网络'},{'english':'network','chinese':'网络'}]
    targets=[]
    for i,text in enumerate(['Neural Network works.','A network trains.']):
        p,m=protect(text,terms);targets.append({'id':str(i),'text':text,'protected':p,'mapping':m})
    out=t.validate_response(json.dumps({'blocks':[{'source_block_id':x['id'],'text':'中文 '+''.join(TOKEN.findall(x['protected']))} for x in reversed(targets)]}),targets)
    assert out['0']=='中文 神经网络' and out['1']=='中文 网络'


def test_locked_overlap_beats_suggestion_and_unicode_case_has_no_lookup_crash():
    protected,mapping=protect('A Neural   Network and İNPUT.',[
        {'english':'neural network','chinese':'建议短语','priority':'suggested'},
        {'english':'network','chinese':'锁定网络','locked':True},
        {'english':'input','chinese':'输入','priority':'confirmed'}])
    assert '锁定网络' in mapping.values() and '建议短语' not in mapping.values()
    assert '输入' in mapping.values()


def test_full_cache_manual_conflict_and_version_scope(client):
    p,f=ready(client)
    g=t.save_glossary(f['paper']['id'],None,[{'english':'PaperMind','chinese':'论文工作台','locked':True,'priority':'confirmed'}])
    r=t.submit(p['id'],'full',[],'one');assert t.submit(p['id'],'full',[],'one')['id']==r['id']
    with pytest.raises(t.Conflict):t.submit(p['id'],'blocks',['wrong'],'one')
    assert r['snapshot']['glossary']['id']==g['id']
    job=queue.claim('translator');t.execute(job,'translator',lambda:False,provider)
    r=t.get_run(r['id']);assert r['status']=='succeeded' and r['counts']['translated']>0
    bid=r['blocks'][0]['block_id'];head=r['blocks'][0]['id']
    edited=t.edit(r['id'],bid,head,'人工改译保留');assert edited['blocks'][0]['result']['manual']
    with pytest.raises(t.Conflict) as exc:t.edit(r['id'],bid,head,'过期编辑')
    assert exc.value.detail['local']=='过期编辑' and exc.value.detail['remote']=='人工改译保留'
    cached=t.submit(p['id'],'blocks',[bid],'two');job=queue.claim('translator')
    t.execute(job,'translator',lambda:False,lambda *args: (_ for _ in ()).throw(AssertionError('cache miss')))
    assert t.get_run(cached['id'])['counts']['cache_hits']==1
    assert t.get_run(r['id'])['blocks'][0]['result']['text']=='人工改译保留'
    t.save_glossary(f['paper']['id'],g['id'],[{'english':'PaperMind','chinese':'新译法','locked':True,'priority':'confirmed'}])
    changed=t.submit(p['id'],'blocks',[bid],'three');job=queue.claim('translator');t.execute(job,'translator',lambda:False,provider)
    assert t.get_run(changed['id'])['counts']['cache_hits']==0
    assert '新译法' in t.get_run(changed['id'])['blocks'][0]['result']['text']


def test_term_conflict_and_snapshot_occ(client):
    p,f=ready(client);pid=f['paper']['id']
    with pytest.raises(ValueError):t.save_glossary(pid,None,[{'english':en,'chinese':zh,'locked':True,'priority':'confirmed'} for en,zh in [('ABC','甲'),('abc','乙')]])
    old=t.save_glossary(pid,None,[])
    with pytest.raises(t.Conflict):t.save_glossary(pid,None,[])
    assert t.glossary(pid)['id']==old['id']


def test_retry_budget_and_stale_owner(client):
    p,f=ready(client);r=t.submit(p['id'],'full',[],'fail');job=queue.claim('old')
    calls=[]
    def bad(*args):calls.append(1);return '{"blocks":[]}',None
    t.execute(job,'old',lambda:False,bad)
    assert len(calls)==3 and t.get_run(r['id'])['counts']['failed']==1
    for i in range(2):
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(available_at=0))
        job=queue.claim('new');t.execute(job,'new',lambda:False,bad)
    assert t.get_run(r['id'])['status']=='failed' and len(calls)==3
    forced=t.submit(p['id'],'full',[],'stale',True);job=queue.claim('stale')
    def expire(*args):
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(lease_expires_at=time.time()-1))
        return provider(*args)
    with pytest.raises(LeaseLost):t.execute(job,'stale',lambda:False,expire)
    assert not t.get_run(forced['id'])['blocks']


def test_table_keeps_coordinates_and_preserve_unknown():
    block={'id':'b','type':'table','data':{'table_model':{'cells':[{'text':'Name','row':0,'column':0,'row_span':2,'column_span':1},{'text':'2.5','row':1,'column':1}]}}}
    items,status,reason=t.units(block);assert len(items)==2 and status is None
    assert t.units({'id':'b','type':'table','data':{}})[1]=='needs_review'
    assert t.units({'id':'b','type':'equation'})[1]=='preserved'


def test_term_extraction_requires_source_and_offsets():
    b={'id':'r/b','text':'🧪 neural network trains.','regions':[{'page_index':0,'bbox':[0,0,1,1]}]}
    raw=json.dumps({'terms':[{'source_block_id':'r/b','english':'neural network','chinese':'神经网络'}]})
    result=t.glossary_response(raw,b)[0];assert b['text'][result['start']:result['end']]=='neural network'
    with pytest.raises(ReadingFailure):t.glossary_response(raw.replace('neural network','invented'),b)


def test_api_no_credentials_and_settings_task_isolation(client):
    p,f=ready(client)
    assert client.get('/v1/task-model-settings/glossary').json()['model']==''
    assert client.post('/v1/task-model-settings/translation',json={'endpoint':'http://127.0.0.1:9999/chat','model':'configured','key_env':'TEST_ONLY_MISSING','expected_revision':t.settings('translation')['revision']}).status_code==200
    r=client.post('/v1/parse-runs/'+p['id']+'/translation-runs',json={'operation_key':'no-key'})
    assert r.status_code==202
    assert client.get('/v1/translation-runs/'+r.json()['id']).status_code==200
    assert client.post('/v1/parse-runs/'+p['id']+'/translation-runs',json={'operation_key':'unknown','scope':'blocks','ids':['not-owned']}).status_code==409


def test_active_duplicate_requests_have_durable_aliases(client):
    p,f=ready(client)
    a=t.submit(p['id'],'full',[],'first-key');b=t.submit(p['id'],'full',[],'second-key')
    assert a['id']==b['id']
    assert t.submit(p['id'],'full',[],'second-key')['id']==a['id']
    with pytest.raises(t.Conflict):t.submit(p['id'],'full',[],'second-key',True)


def test_reparse_never_reuses_prior_identity(client):
    p,f=ready(client);old=t.submit(p['id'],'full',[],'old')
    job=queue.claim('old');t.execute(job,'old',lambda:False,provider)
    new=create(client,f['file_id'],force=True);run(new)
    r=t.submit(new['id'],'full',[],'new');job=queue.claim('new');t.execute(job,'new',lambda:False,provider)
    assert t.get_run(r['id'])['counts']['cache_hits']==0
    assert set(b['id'] for b in r['snapshot']['blocks']).isdisjoint(b['id'] for b in old['snapshot']['blocks'])


def test_table_response_reverses_cells_preserves_spans_and_values(client,monkeypatch):
    p,f=ready(client);doc,file=t.source(p['id']);block=doc['blocks'][0]
    block.update(type='table',data={'table_model':{'num_rows':2,'num_columns':2,'cells':[
        {'row':0,'column':0,'row_span':2,'column_span':1,'text':'network'},
        {'row':1,'column':1,'row_span':1,'column_span':1,'text':'-2.3e-5 ms'}]}})
    monkeypatch.setattr(t,'source',lambda pid:(doc,file))
    r=t.submit(p['id'],'full',[],'table');job=queue.claim('table');t.execute(job,'table',lambda:False,provider)
    end=t.get_run(r['id']);cells=end['blocks'][0]['result']['table']['cells']
    assert end['status']=='succeeded' and cells[0]['row_span']==2
    assert cells[1]['column']==1 and '-2.3e-5 ms' in cells[1]['text']
    assert block['data']['table_model']['cells'][1]['text']=='-2.3e-5 ms'


def test_oversized_block_preserves_whole_source_without_request(client,monkeypatch):
    p,f=ready(client);doc,file=t.source(p['id']);doc['blocks'][0]['text']='long source '*1500
    monkeypatch.setattr(t,'source',lambda pid:(doc,file))
    r=t.submit(p['id'],'full',[],'large');job=queue.claim('large')
    t.execute(job,'large',lambda:False,lambda *a:(_ for _ in ()).throw(AssertionError('Oversized request')))
    end=t.get_run(r['id']);assert end['counts']['needs_review']==1 and not end['batches']
    assert end['blocks'][0]['result']['text']==doc['blocks'][0]['text']


def test_context_is_bounded_and_cannot_be_counted_as_target(client,monkeypatch):
    p,f=ready(client);doc,file=t.source(p['id']);original=doc['blocks'][0]
    neighbor={**original,'id':original['id']+'-context','reading_order':original['reading_order']+1,'text':'Context with $x < y$ and -2 ms. '*40}
    doc['blocks'].append(neighbor)
    monkeypatch.setattr(t,'source',lambda pid:(doc,file))
    r=t.submit(p['id'],'blocks',[original['id']],'context');job=queue.claim('context')
    def wrong_context(config,messages,cancelled):
        body=json.loads(messages[-1]['content']);ctx=body['context'][0]
        assert ctx['source_block_id']==neighbor['id'] and ctx['context_only']
        assert ctx['end']==400 and len(body['targets'])==1
        assert '$x < y$' not in ctx['text'] and '-2 ms' not in ctx['text']
        return json.dumps({'blocks':[{'source_block_id':ctx['source_block_id'],'text':'上下文不应计入译文'}]}),None
    t.execute(job,'context',lambda:False,wrong_context)
    end=t.get_run(r['id']);assert end['counts']['failed']==1 and end['counts']['translated']==0
