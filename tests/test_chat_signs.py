import copy
import json
from pathlib import Path
import pymupdf
import pytest
from sqlalchemy import select,func
from backend import chat,chat_sources,parsing,queue,reading
from backend.db import engine,write_tx,jobs,chat_turns,chat_messages
from backend.reading_provider import ReadingFailure
from test_parsing import uploaded,create,run
from test_chat import run_turn,choose

def actual_pdf(client,text,font=None):
    pdf=pymupdf.open();page=pdf.new_page()
    if font:
        path=Path('C:/Windows/Fonts')/font
        if not path.is_file():pytest.skip('Windows font unavailable')
        page.insert_font(fontname='F0',fontfile=str(path));page.insert_text((50,90),text,fontname='F0',fontsize=12)
        pdf.subset_fonts()
    else:page.insert_text((50,90),text,fontsize=12)
    raw=pdf.tobytes(deflate=True);pdf.close();assert len(raw)<65536
    file=uploaded(client,raw);parsed=create(client,file['file_id']);assert run(parsed)['status']=='succeeded'
    reading.configure({'endpoint':'http://127.0.0.1:9999/unused','model':'protocol-test-only'})
    return parsed

def description(p,text):
    return {'parse_run_id':p['id'],'paper_file_id':p['paper_file_id'],'file_sha256':p['file_sha256'],
        'page_index':0,'text':text,'layer_text':text,'layer_start':0,'layer_end':len(text)}

def mapped(client,p,text):
    selected=description(p,text)
    response=client.post('/v1/parse-runs/'+p['id']+'/selection-map',json=selected)
    assert response.status_code==200,response.text
    return selected,response.json()

@pytest.mark.parametrize('actual,forged',[
    ('The measured change is 3 percent.','The measured change is -3 percent.'),
    ('The measured change is -3 percent.','The measured change is 3 percent.'),
    ('The expression is x-y.','The expression is xy.'),
    ('The expression is xy.','The expression is x-y.'),
    ('The rate is 1e-3.','The rate is 1e3.'),
    ('The rate is 1e3.','The rate is 1e-3.'),
    ('The interval is 3-5.','The interval is 35.'),
    ('The value is 3.5.','The value is 35.'),
    ('The values are 3,5.','The values are 35.'),
    ('The function is f(x).','The function is fx.'),
    ('The fields are 1 2.','The fields are 12.'),
    ('The fields are 12.','The fields are 1 2.'),
])
def test_real_pdf_api_signs_and_punctuation_not_interchangeable(client,actual,forged):
    p=actual_pdf(client,actual);valid,result=mapped(client,p,actual)
    assert result['status']=='matched'
    assert result['source_version']==chat_sources.SOURCE_VERSION
    candidate=result['candidates'][0];valid['candidate_id']=candidate['candidate_id']
    assert candidate['source'][0]['text']==actual
    assert candidate['candidate_id']!=reading.digest(candidate['source'])
    sid=client.post('/v1/chat-sessions',json={'parse_run_id':p['id']}).json()['id']
    forged_input,bad=mapped(client,p,forged)
    assert bad['status']=='unmatched' and bad['candidates']==[]
    with engine.connect() as c:before=c.scalar(select(func.count()).select_from(jobs))
    forged_input['candidate_id']=valid['candidate_id']
    rejected=client.post('/v1/chat-sessions/'+sid+'/messages',json={'question':'protocol test','idempotency_key':'wrong-sign-key','selection':forged_input})
    assert rejected.status_code==409
    assert client.get('/v1/chat-sessions/'+sid+'/messages').json()==[]
    with engine.connect() as c:assert c.scalar(select(func.count()).select_from(jobs))==before
    accepted=client.post('/v1/chat-sessions/'+sid+'/messages',json={'question':'protocol test','idempotency_key':'correct-sign-key','selection':valid})
    assert accepted.status_code==202,accepted.text
    turn=accepted.json();assert turn['snapshot']['source_version']==chat_sources.SOURCE_VERSION
    assert turn['snapshot']['source'][0]['text']==actual
    run_turn(turn)
    assert chat.messages(sid)[-1]['data']['source_version']==chat_sources.SOURCE_VERSION

@pytest.mark.parametrize('actual,selected,font',[
    ('The   measured change is 3 percent.','The measured change is 3 percent.',None),
    ('The well-\nknown method works.','The well-known method works.',None),
    ('We co\u00ad\noperate today.','We co\u00adoperate today.','segoeui.ttf'),
    ('office ﬁne e\u0301 m²','office fine é m²','segoeui.ttf'),
    ('ＡＢＣ ３ 中文 m²','ABC 3 中文 m²','msyh.ttc'),
    ('The change is −3 percent.','The change is −3 percent.','segoeui.ttf'),
])
def test_real_pdf_safe_layout_and_presentation_compatibility(client,actual,selected,font):
    p=actual_pdf(client,actual,font);_,result=mapped(client,p,selected)
    assert result['status']=='matched',result
    doc=parsing.structure(p['id']);blocks={b['id']:b for b in doc['blocks']}
    for source in result['candidates'][0]['source']:
        assert source['text']==blocks[source['block_id']]['text'][source['start']:source['end']]
    if '-' in actual:assert '-' in result['candidates'][0]['preview']
    if '\u00ad' in actual:assert '\u00ad' in result['candidates'][0]['preview']

@pytest.mark.parametrize('actual,forged,font',[
    ('The well-\nknown method works.','The wellknown method works.',None),
    ('The expression is x-\ny.','The expression is xy.',None),
    ('We co\u00adoperate today.','We cooperate today.','segoeui.ttf'),
    ('The area is m².','The area is m2.','segoeui.ttf'),
    ('The change is -3 percent.','3 percent.',None),
    ('The change is - 3 percent.','3 percent.',None),
])
def test_ambiguous_wrap_soft_hyphen_power_and_signed_substring_rejected(client,actual,forged,font):
    p=actual_pdf(client,actual,font);_,result=mapped(client,p,forged)
    assert result['status']=='unmatched'

def test_legacy_candidate_history_and_idempotency_do_not_upgrade_silently(client):
    p=actual_pdf(client,'The measured change is 3 percent.');valid,result=mapped(client,p,'The measured change is 3 percent.')
    valid['candidate_id']=result['candidates'][0]['candidate_id'];sid=chat.create_session(p['id'])['id']
    old=chat.submit(sid,'old question','legacy-key-000',valid);run_turn(old)
    legacy=copy.deepcopy(old['snapshot']);legacy['source_version']='chat-source-1'
    legacy['selection']['candidate_id']=reading.digest(legacy['selection']['source'])
    with write_tx() as c:
        c.execute(chat_turns.update().where(chat_turns.c.id==old['id']).values(snapshot=legacy))
        for row in c.execute(select(chat_messages).where(chat_messages.c.turn_id==old['id'])).mappings():
            data=dict(row['data']);data.pop('source_version',None)
            c.execute(chat_messages.update().where(chat_messages.c.id==row['id']).values(data=data))
    before=chat.messages(sid)
    assert client.get('/v1/chat-turns/'+old['id']).status_code==200
    with pytest.raises(ReadingFailure,match='旧版选文'):
        chat.submit(sid,'reuse legacy','reuse-legacy-key',reuse_selection_turn_id=old['id'])
    with pytest.raises(ReadingFailure,match='旧契约幂等键'):chat.submit(sid,'old question','legacy-key-000',valid)
    expired={**valid,'candidate_id':legacy['selection']['candidate_id']}
    with pytest.raises(ReadingFailure,match='过期'):chat.submit(sid,'stale candidate','old-candidate-key',expired)
    assert chat.messages(sid)==before
    fresh=chat.submit(sid,'fresh question','fresh-new-key-000',valid)
    assert fresh['id']!=old['id'] and fresh['snapshot']['source_version']==chat_sources.SOURCE_VERSION

@pytest.mark.parametrize('mode',['legacy','tampered_current'])
def test_pending_bad_selection_cannot_call_model(client,mode):
    p=actual_pdf(client,'The measured change is 3 percent.');valid,result=mapped(client,p,'The measured change is 3 percent.')
    valid['candidate_id']=result['candidates'][0]['candidate_id'];sid=chat.create_session(p['id'])['id']
    turn=chat.submit(sid,'protocol test','pending-sign-key',valid)
    snap=copy.deepcopy(turn['snapshot']);snap['selection']['text']='The measured change is -3 percent.'
    if mode=='legacy':snap['source_version']='chat-source-1'
    with write_tx() as c:c.execute(chat_turns.update().where(chat_turns.c.id==turn['id']).values(snapshot=snap))
    calls=[]
    def forbidden(*args):calls.append(1);raise AssertionError('model must not be called')
    for attempt in range(3):
        job=queue.claim('reject-worker')
        with pytest.raises(ReadingFailure) as exc:chat.execute(job,'reject-worker',lambda:False,forbidden)
        queue.finish(job['id'],'reject-worker',error=str(exc.value))
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(available_at=0))
    assert not calls and chat.turn(turn['id'])['status']=='failed'
    assert chat.messages(sid)[-1]['status']=='failed'
    assert all(e['type']=='failed' for e in chat.events(turn['id']))
