import json
import time
import pytest
from sqlalchemy import select
from backend import reading,queue
from backend.db import engine,write_tx,reading_stages,reading_runs
from backend.reading_provider import ReadingFailure
from test_reading import ready,provider

def fixture_doc():
    text='A'*6000+'B'*6000+'Unique tail sentence never sent in first stage.'
    block={'id':'parse-a:block','parse_run_id':'parse-a','section_id':None,'text':text,
           'regions':[{'page_index':0,'bbox':[0,0,.5,.5]},{'page_index':1,'bbox':[0,0,.5,.5]}],
           'quality_flags':['unreviewed']}
    return {'run':{'id':'parse-a'},'sections':[],'blocks':[block]}

def response(bid,quote):
    return json.dumps({'summary':'protocol fixture only','claims':[{'text':'fixture claim','kind':'fact',
        'verification':'supported','evidence':[{'block_id':bid,'quote':quote}]}]})

@pytest.mark.parametrize('case',['correct','unsent_tail','wrong_quote','different_block','different_run',
                               'forged_fragment_text','wrong_offset','missing_region','boundary_quote'])
def test_exact_sent_fragment_boundary_and_multi_region(case):
    doc=fixture_doc();block=doc['blocks'][0];source=reading.plan(doc)[0]['source']
    quote='A'*20;bid=block['id'];rid='parse-a'
    if case=='unsent_tail':quote='Unique tail sentence never sent in first stage.'
    if case=='wrong_quote':quote='wrong text here'
    if case=='different_block':bid='parse-a:other'
    if case=='different_run':rid='parse-b'
    if case=='forged_fragment_text':source[0]['text']='FORGED TEXT AT LEAST 8';quote=source[0]['text']
    if case=='wrong_offset':source[0]['start']=1
    if case=='missing_region':block['regions']=[]
    if case=='boundary_quote':quote='A'*10+'B'*10
    result=reading.validate_output(response(bid,quote),{block['id']:block},source,rid)['claims'][0]
    assert result['evidence'][0]['matched']==(case=='correct')
    assert result['verification']==('unreviewed' if case=='correct' else 'unsupported')
    if case=='correct':
        evidence=result['evidence'][0]
        assert len(evidence['regions'])==2
        for match in evidence['source_fragments']:
            assert match['parse_run_id']=='parse-a'
            assert block['text'][match['quote_start']:match['quote_end']]==quote
            assert match['quote_end']<=match['end']<=6000
    else:assert result['evidence'][0]['source_fragments']==[]

def test_new_contract_invalidates_legacy_stage_and_revalidates(client):
    p=ready(client);r=reading.submit(p['id']);job=queue.claim('reader')
    doc=reading.parsing.structure(p['id']);stage=reading.plan(doc)[0]
    with write_tx() as c:
        c.execute(reading_stages.insert().values(run_id=r['id'],stage_key=stage['key'],
            result={'summary':'LEGACY_MUST_NOT_REUSE','claims':[{'verification':'supported'}]}))
    calls=[]
    def fresh(*args):calls.append(1);return provider(*args)
    reading.execute(job,'reader',lambda _:None,lambda:False,fresh)
    assert calls
    report=reading.report(r['id'])
    assert report['evidence_contract']==reading.EVIDENCE_CONTRACT
    assert 'LEGACY_MUST_NOT_REUSE' not in json.dumps(report)
    with engine.connect() as c:
        cache=c.execute(select(reading_stages.c.result).where(reading_stages.c.run_id==r['id'])).scalar()
    assert cache['evidence_contract']==reading.EVIDENCE_CONTRACT and cache['source_sha256']==reading.digest(stage['source'])
    assert cache['source']==stage['source']

def test_legacy_pending_requires_new_run_but_legacy_public_report_unchanged(client):
    p=ready(client);old=reading.submit(p['id']);job=queue.claim('reader')
    reading.execute(job,'reader',lambda _:None,lambda:False,provider)
    before=reading.report(old['id'])
    pending=reading.submit(p['id'],True)
    legacy=dict(pending['config']);legacy.pop('evidence_contract');legacy['prompt_version']='reading-v1-evidence-1'
    legacy_hash=reading.digest({'parse_run_id':p['id'],'pdf_sha256':p['file_sha256'],'config':legacy})
    with write_tx() as c:c.execute(reading_runs.update().where(reading_runs.c.id==pending['id']).values(config=legacy,input_hash=legacy_hash))
    old_job=queue.claim('legacy')
    def must_not_call(*args):raise AssertionError('Old contract sent to model')
    with pytest.raises(ReadingFailure,match='旧精读任务'):reading.execute(old_job,'legacy',lambda _:None,lambda:False,must_not_call)
    fresh=reading.submit(p['id'],True)
    assert fresh['id']!=pending['id'] and fresh['input_hash']!=legacy_hash
    assert reading.report(old['id'])==before
    assert client.get('/v1/reading-runs/'+pending['id']+'/report').status_code==409
