import copy,json,os,re,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest,yaml
from sqlalchemy import create_engine,inspect,select
from backend import notes,note_exports,reading,chat,parsing,queue
from backend.db import (engine,write_tx,STORAGE,meta,migrate,SCHEMA_VERSION,jobs,chat_messages,chat_turns)
from test_parsing import uploaded,create,run
from test_reading import provider
from test_chat import run_turn

def setup_note(client,read=False,image=False):
    f=uploaded(client);p=create(client,f['file_id'])
    def converter(path,rid,config,work,progress):
        import pymupdf
        from backend.parse_pipeline import native_parse
        output=native_parse(path,rid,config,work,progress)
        with pymupdf.open(path) as pdf:pdf[0].get_pixmap().save(work/'图 像.png')
        output['blocks'][0]['data']['assets']=['图 像.png']
        return output
    if image:assert run(p,converter=converter)['status']=='succeeded'
    else:assert run(p)['status']=='succeeded'
    reading_id=None
    if read:
        reading.configure({'endpoint':'http://127.0.0.1:9999/test','model':'notes-protocol-only'})
        r=reading.submit(p['id']);j=queue.claim('read-notes');reading.execute(j,'read-notes',lambda v:None,lambda:False,provider);reading_id=r['id']
    rev=notes.create(f['file_id'],p['id'],reading_id,key='create-note-key')
    return rev,p,reading_id

def edit(rev,text='handwritten 中文😀 $x^{-2}$',sid='s05',key='edit-note-key'):
    return notes.edit(rev['note_id'],rev['id'],key,sid,text)
def approved(rev):return notes.review(rev['note_id'],rev['id'],rev['content_hash'])
def vault(tmp_path):
    root=tmp_path/'隔离 笔记Vault';root.mkdir();return note_exports.configure(str(root),'受管笔记',None)
def plan(rev,key='publish-preview-key',fork=False):return note_exports.preview(rev['note_id'],rev['id'],rev['content_hash'],key,fork)
def target(record):return Path(record['plan']['config']['root'])/record['plan']['config']['subdir']/record['plan']['target']

def test_vault_uses_readable_title_and_reserves_collisions(client,tmp_path):
    rev,_,_=setup_note(client)
    fid=rev['note']['paper_file_id'];parse_id=rev['note']['parse_run_id']
    a=approved(notes.create(fid,parse_id,title='原论文：Methods / Results?',key='readable-note-a'))
    b=approved(notes.create(fid,parse_id,title='原论文：METHODS / RESULTS?',key='readable-note-b'))
    config=vault(tmp_path)
    folder=Path(config['root'])/config['subdir'];folder.mkdir()
    external=folder/'原论文：methods Results.md'
    external.write_text('keep this',encoding='utf8')
    first=plan(a,key='readable-preview-a')
    second=plan(b,key='readable-preview-b')
    assert target(first).name=='原论文：Methods Results（2）.md'
    assert target(second).name=='原论文：METHODS RESULTS（3）.md'
    note_exports.commit(first['id']);note_exports.commit(second['id'])
    assert external.read_text(encoding='utf8')=='keep this'
    assert note_exports.title_filename('CON.txt')=='论文 CON.txt.md'
    assert len(note_exports.title_filename('文'*200,2))==120

def test_notes_reading_handwriting_suggestions_versions_review_and_yaml(client,monkeypatch):
    rev,p,read=setup_note(client,read=True)
    assert len(rev['snapshot']['sections'])==12 and not rev['reviewed']
    first=copy.deepcopy(rev);manual=edit(rev,'## 手写\n\n|列|值|\n|---|---|\n|A|3|\n\n$$\nx^{-2}\n$$\n\n```py\nprint(1)\n```\n[[知识]]')
    suggestions=notes.suggestions(rev['note_id'],read)
    assert notes.revision(rev['note_id'])==manual
    assert suggestions['changes'][1]['current']==manual['snapshot']['sections'][4]['markdown']
    imported=notes.apply_reading(rev['note_id'],manual['id'],'apply-only-contribution',read,['s02'])
    assert imported['snapshot']['sections'][4]==manual['snapshot']['sections'][4]
    assert imported['snapshot']['sections'][4]['manual']
    reviewed=approved(imported);assert reviewed['reviewed']
    changed=edit(reviewed,'new handwritten text',key='edit-after-review')
    assert not changed['reviewed']
    with pytest.raises(notes.Conflict):notes.review(changed['note_id'],reviewed['id'],reviewed['content_hash'])
    restored=notes.restore(changed['note_id'],changed['id'],'restore-note-key',first['id'])
    assert restored['snapshot']==first['snapshot'] and not restored['reviewed'] and restored['id']!=first['id']
    assert len(notes.versions(rev['note_id']))==5
    assert '手写' in notes.difference(rev['note_id'],first['id'],manual['id'])['diff']
    malicious='中文: "标题"\nstatus: injected\n---\n<script>bad</script>'
    other=notes.create(p['paper_file_id'],p['id'],title=malicious,key='yaml-title-note')
    front=other['markdown'].split('---\n',2)[1];data=yaml.safe_load(front)
    assert data['title']==malicious and data['status']=='needs-review' and data['year'] is None
    monkeypatch.setattr(reading,'complete',lambda *a:pytest.fail('implicit model call'))
    notes.suggestions(other['note_id'],read);approved(other)

def test_notes_concurrency_idempotency_and_api_conflict_preserve_both(client):
    rev,p,_=setup_note(client)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda i:client.patch('/v1/notes/'+rev['note_id']+'/sections',json={'expected_revision':rev['id'],
            'operation_key':'two-windows-'+str(i),'section_id':'s05','markdown':'window '+str(i)}),range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    conflict=next(r.json()['detail'] for r in results if r.status_code==409)
    assert conflict['submitted']['markdown']!=conflict['current']['sections'][4]['markdown']
    winner=next(r.json() for r in results if r.status_code==200)
    replay=notes.edit(rev['note_id'],rev['id'],'two-windows-'+winner['snapshot']['sections'][4]['markdown'][-1],'s05',winner['snapshot']['sections'][4]['markdown'])
    assert replay['id']==winner['id'] and len(notes.versions(rev['note_id']))==2
    with pytest.raises(ValueError):notes.edit(rev['note_id'],winner['id'],'two-windows-'+winner['snapshot']['sections'][4]['markdown'][-1],'s05','different')
    same=notes.create(p['paper_file_id'],p['id'],key='create-note-key');assert same['note_id']==rev['note_id']

def test_complete_answer_append_old_contract_and_no_source_mutation(client):
    rev,p,_=setup_note(client);reading.configure({'endpoint':'http://127.0.0.1:9999/test','model':'notes-protocol-only'})
    sid=chat.create_session(p['id'])['id'];turn=chat.submit(sid,'protocol','answer-save-key')
    with pytest.raises(ValueError):notes.answer_preview(rev['note_id'],turn['assistant_message_id'])
    run_turn(turn)
    # Controlled old-contract complete history: preserve its original status and snapshots.
    with write_tx() as c:
        snap={**chat.turn(turn['id'])['snapshot'],'source_version':'chat-source-1'}
        c.execute(chat_turns.update().where(chat_turns.c.id==turn['id']).values(snapshot=snap))
    before=chat.messages(sid);preview=notes.answer_preview(rev['note_id'],turn['assistant_message_id'])
    assert '旧版' in preview['warning'] and before[-1]['content'] in preview['markdown']
    handwritten=edit(rev,'keep handwritten')
    saved=notes.save_answer(rev['note_id'],handwritten['id'],'save-answer-key','s07',turn['assistant_message_id'])
    assert saved['snapshot']['sections'][4]['markdown']=='keep handwritten'
    assert before[-1]['content'] in saved['snapshot']['sections'][6]['markdown']
    assert saved['snapshot']['sections'][6]['origins'][0]['source_version']=='chat-source-1'
    again=notes.save_answer(rev['note_id'],handwritten['id'],'save-answer-key','s07',turn['assistant_message_id']);assert again['id']==saved['id']
    deliberate=notes.save_answer(rev['note_id'],saved['id'],'save-answer-again','s07',turn['assistant_message_id'])
    assert deliberate['snapshot']['sections'][6]['markdown'].count(before[-1]['content'])==2
    assert chat.messages(sid)==before
    other=notes.create(p['paper_file_id'],None,key='without-parse-note')
    with pytest.raises(ValueError):notes.answer_preview(other['note_id'],turn['assistant_message_id'])

def test_export_offline_image_pdf_approved_exact_version_and_idempotency(client,tmp_path):
    rev,p,_=setup_note(client,read=True,image=True);config=vault(tmp_path)
    asset=notes.assets(rev['note_id'])[0];rev=edit(rev,'手写与原文\n\n![中文 图](asset:'+asset['id']+')\n\n[[已有知识]]\n\n$x^{-2}$')
    with pytest.raises(notes.Conflict):plan(rev)
    rev=approved(rev);record=plan(rev)
    assert not (Path(config['root'])/config['subdir']).exists()
    result=note_exports.commit(record['id']);assert result['status']=='succeeded'
    path=target(result);text=path.read_text(encoding='utf-8')
    assert '#page=1' in text and 'localhost' not in text and '[[已有知识]]' in text and '$x^{-2}$' in text
    assert len(record['plan']['files'])==2
    for resource in record['plan']['files']:
        file=path.parent/resource['relative'];assert file.is_file() and note_exports.digest_bytes(file.read_bytes())==resource['sha256']
    assert note_exports.commit(record['id'])==result
    assert plan(rev)['id']==record['id']
    newer=edit(rev,'newer revision',key='new-revision-edit')
    with pytest.raises(notes.Conflict):plan(rev,key='stale-reviewed-publish')
    assert path.read_text(encoding='utf-8')==text and not newer['reviewed']

@pytest.mark.parametrize('change',['edit','delete','replace_directory'])
def test_vault_external_changes_keep_both_and_fork(client,tmp_path,change):
    rev,_,_=setup_note(client);vault(tmp_path);rev=approved(rev);published=note_exports.commit(plan(rev)['id']);old=target(published)
    rev=approved(edit(rev,'new local manual revision'))
    if change=='edit':old.write_text('Obsidian external handwritten content',encoding='utf-8')
    else:
        old.unlink()
        if change=='replace_directory':old.mkdir()
    with pytest.raises((notes.Conflict,ValueError)):plan(rev,key='external-conflict')
    fork=note_exports.commit(plan(rev,key='keep-external-and-fork',fork=True)['id'])
    assert target(fork).is_file() and target(fork)!=old
    if change=='edit':assert old.read_text()=='Obsidian external handwritten content'
    elif change=='delete':assert not old.exists()
    else:assert old.is_dir()

def test_unmanaged_name_and_baseline_change_after_preview(client,tmp_path):
    rev,_,_=setup_note(client);vault(tmp_path);rev=approved(rev);record=plan(rev);path=target(record)
    path.parent.mkdir(parents=True);path.write_text(record['plan']['markdown'],encoding='utf-8')
    with pytest.raises(notes.Conflict):note_exports.commit(record['id'])
    assert note_exports.get(record['id'])['status']=='preview'
    second=note_exports.commit(plan(rev,key='unmanaged-fork',fork=True)['id']);current=target(second)
    new=approved(edit(rev,'a new revision'));prepared=plan(new,key='preview-before-external-change')
    current.write_text('external changed after preview',encoding='utf-8')
    with pytest.raises(notes.Conflict):note_exports.commit(prepared['id'])
    assert not target(prepared).exists() and current.read_text()=='external changed after preview'

@pytest.mark.parametrize('stage',['resource','markdown','database_commit'])
def test_export_injected_failures_recover_without_false_success(client,tmp_path,monkeypatch,stage):
    rev,_,_=setup_note(client);vault(tmp_path);rev=approved(rev);record=plan(rev)
    def fail(current):
        if current==stage:raise OSError('controlled publish failure')
    monkeypatch.setattr(note_exports,'fault',fail)
    with pytest.raises(OSError):note_exports.commit(record['id'])
    assert note_exports.get(record['id'])['status']=='failed'
    monkeypatch.setattr(note_exports,'fault',lambda stage:None)
    assert note_exports.commit(record['id'])['status']=='succeeded'
    assert target(record).read_text(encoding='utf-8')==record['plan']['markdown']

def test_actual_process_crash_after_markdown_and_explicit_resume(client,tmp_path):
    rev,_,_=setup_note(client);vault(tmp_path);record=plan(approved(rev))
    code="from backend import note_exports as e; e.fault=lambda stage: __import__('os')._exit(73) if stage=='markdown' else None; e.commit("+repr(record['id'])+")"
    env=os.environ.copy();env['PAPERMIND_STORAGE']=str(STORAGE)
    child=subprocess.run([sys.executable,'-c',code],cwd=Path.cwd(),env=env,capture_output=True,timeout=15)
    assert child.returncode==73,child.stderr
    assert note_exports.get(record['id'])['status']=='preparing' and target(record).is_file()
    assert note_exports.commit(record['id'])['status']=='succeeded'

def test_concurrent_commit_and_failed_copy_leave_previous_success(client,tmp_path,monkeypatch):
    rev,_,_=setup_note(client);vault(tmp_path);rev=approved(rev);record=plan(rev)
    with ThreadPoolExecutor(3) as pool:results=list(pool.map(lambda _:note_exports.commit(record['id']),range(3)))
    assert all(r['status']=='succeeded' for r in results)
    old=target(record).read_bytes();new=approved(edit(rev,'new manual revision'));next_record=plan(new,key='new-publish-key')
    def fail(*a):raise PermissionError('controlled denied')
    monkeypatch.setattr(note_exports,'durable_new',fail)
    with pytest.raises(PermissionError):note_exports.commit(next_record['id'])
    assert note_exports.get(next_record['id'])['status']=='failed' and target(record).read_bytes()==old and not target(next_record).exists()

@pytest.mark.parametrize('subdir',['../escape','/absolute','C:/escape','a\\b','a:stream','CON','A/NUL.md','trailing.','trailing ','a//b','//server/share'])
def test_vault_path_boundaries(client,tmp_path,subdir):
    with pytest.raises(ValueError):note_exports.configure(str(tmp_path),subdir,None)
    assert not note_exports.settings()['configured']

def test_actual_junction_and_source_whitelist(client,tmp_path):
    if os.name!='nt':pytest.skip('Windows junction test')
    base=tmp_path/'vault';outside=tmp_path/'external';base.mkdir();outside.mkdir();junction=base/'escape'
    result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],capture_output=True)
    assert result.returncode==0,result.stderr
    try:
        with pytest.raises(ValueError,match='reparse'):note_exports.configure(str(base),'escape/sub',None)
    finally:os.rmdir(junction)
    rev,_,_=setup_note(client);vault(tmp_path)
    for text in ['![bad](asset:fake)','![bad](file:///C:/secret.png)','![bad](https://example.invalid/image.png)']:
        next_rev=approved(edit(rev,text,key='bad-resource-'+str(len(text))))
        with pytest.raises(ValueError,match='图片'):plan(next_rev,key='bad-plan-'+str(len(text)))
        rev=next_rev

def test_vault_probe_settings_no_publish_and_tampered_resource(client,tmp_path):
    rev,_,_=setup_note(client);root=tmp_path/'vault';root.mkdir()
    assert note_exports.validate(str(root),'输出')['valid'] and list(root.iterdir())==[]
    note_exports.configure(str(root),'输出',None)
    record=plan(approved(rev));published=note_exports.commit(record['id'])
    resource=target(record).parent/record['plan']['files'][0]['relative'];resource.write_bytes(b'external changed resource')
    newer=approved(edit(rev,'new revision'))
    attempted=plan(newer,key='resource-tamper-key')
    with pytest.raises(notes.Conflict,match='资源'):note_exports.commit(attempted['id'])
    assert resource.read_bytes()==b'external changed resource' and target(published).is_file()

def test_missing_image_and_changed_pdf_fail_before_publish(client,tmp_path):
    rev,p,_=setup_note(client,image=True);vault(tmp_path);asset=notes.assets(rev['note_id'])[0]
    rev=approved(edit(rev,'![image](asset:'+asset['id']+')'))
    from backend.files import file_path
    root=file_path(parsing.get_run(p['id'])['artifact_root']);image=root/asset['name'];raw=image.read_bytes();image.unlink()
    with pytest.raises(ValueError,match='不存在'):plan(rev)
    image.write_bytes(raw)
    record=plan(rev);image.write_bytes(b'changed after preview')
    with pytest.raises(ValueError,match='哈希'):note_exports.commit(record['id'])
    assert note_exports.get(record['id'])['status']=='failed' and not target(record).exists()

def test_reviewed_preview_invalidated_by_edit_or_settings_change(client,tmp_path):
    rev,_,_=setup_note(client);config=vault(tmp_path);rev=approved(rev);record=plan(rev)
    edit(rev,'newer saved version')
    with pytest.raises(notes.Conflict):note_exports.commit(record['id'])
    assert not target(record).exists()
    other=tmp_path/'different';other.mkdir()
    note_exports.configure(str(other),'PaperMind',config['revision'])
    with pytest.raises(notes.Conflict):note_exports.commit(record['id'])

def test_v4_to_v5_migration_rollback_repeatable_and_immutable_rows(tmp_path):
    target_engine=create_engine('sqlite:///'+str(tmp_path/'v4.sqlite3'))
    new={'notes','note_revisions','note_operations','note_reviews','vault_settings','note_exports'}
    old=[t for t in meta.sorted_tables if t.name not in new];meta.create_all(target_engine,tables=old)
    from backend.db import schema_migrations
    with target_engine.begin() as c:
        c.execute(schema_migrations.insert(),[{'version':i,'applied_at':i} for i in range(1,5)]);c.exec_driver_sql('pragma user_version=4')
    before=set(inspect(target_engine).get_table_names())
    def fail(c):raise RuntimeError('controlled v5 migration failure')
    with pytest.raises(RuntimeError):migrate(target_engine,after_ddl=fail)
    assert set(inspect(target_engine).get_table_names())==before
    with target_engine.connect() as c:assert c.exec_driver_sql('pragma user_version').scalar()==4
    migrate(target_engine);migrate(target_engine)
    with target_engine.connect() as c:assert c.exec_driver_sql('pragma user_version').scalar()==SCHEMA_VERSION==6
    assert new<=set(inspect(target_engine).get_table_names());target_engine.dispose()
