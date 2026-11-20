import json
from sqlalchemy import create_engine,inspect,select
import pytest
from backend.db import meta,papers,paper_files,jobs,job_events,migrate,schema_migrations

def v1_database(tmp_path):
    target=create_engine('sqlite:///'+str(tmp_path/'v1.sqlite3'))
    legacy=[papers,paper_files,jobs,job_events]
    meta.create_all(target,tables=legacy)
    with target.begin() as c:
        c.execute(papers.insert().values(id='old-paper',title='Existing paper',created_at=1))
        c.execute(paper_files.insert().values(id='old-file',paper_id='old-paper',sha256='a'*64,
            relative_path='pdf/a.pdf',version=1,source='upload',size=120,pages=2,created_at=1))
        c.execute(jobs.insert().values(id='old-job',type='arxiv_import',status='succeeded',payload={},
            attempts=1,max_attempts=3,available_at=1,created_at=1,updated_at=2))
        c.execute(job_events.insert().values(id=17,job_id='old-job',type='succeeded',data={'ok':True},created_at=2))
    return target,legacy

def read_legacy(target,tables):
    with target.connect() as c:
        return {t.name:[dict(r) for r in c.execute(select(t)).mappings()] for t in tables}

def test_migration_preserves_v1_and_is_repeatable(tmp_path):
    target,legacy=v1_database(tmp_path)
    try:
        before=read_legacy(target,legacy)
        migrate(target);migrate(target)
        assert read_legacy(target,legacy)==before
        with target.connect() as c:
            assert set(c.execute(select(schema_migrations.c.version)).scalars())=={1,2,3,4,5,6}
            assert c.exec_driver_sql('PRAGMA user_version').scalar()==6
        assert {'parse_runs','document_sections','document_blocks','file_parse_heads'}<=set(inspect(target).get_table_names())
    finally:target.dispose()

def test_migration_failure_rolls_back_ddl_and_retries(tmp_path):
    target,legacy=v1_database(tmp_path)
    try:
        before=read_legacy(target,legacy)
        tables=set(inspect(target).get_table_names())
        def fail(conn):raise RuntimeError('controlled migration failure')
        with pytest.raises(RuntimeError,match='controlled'):
            migrate(target,after_ddl=fail)
        assert set(inspect(target).get_table_names())==tables
        assert read_legacy(target,legacy)==before
        migrate(target)
        assert read_legacy(target,legacy)==before
    finally:target.dispose()

def test_v2_to_v3_preserves_parse_identity_and_rolls_back_new_tables(tmp_path):
    from backend.db import parse_runs,document_sections,document_blocks,file_parse_heads
    target,legacy=v1_database(tmp_path)
    old=legacy+[schema_migrations,parse_runs,document_sections,document_blocks,file_parse_heads]
    try:
        meta.create_all(target,tables=old)
        with target.begin() as c:
            c.execute(schema_migrations.insert(),[{'version':1,'applied_at':1},{'version':2,'applied_at':2}])
            c.exec_driver_sql('PRAGMA user_version=2')
            c.execute(parse_runs.insert().values(id='old-parse',paper_file_id='old-file',job_id='old-job',
                file_sha256='a'*64,input_hash='b'*64,parser='native',parser_version='1',config_version='old',
                config={},status='succeeded',created_at=2))
            c.execute(document_sections.insert().values(id='old-section',parse_run_id='old-parse',title='Method',level=1,reading_order=0,regions=[]))
            c.execute(document_blocks.insert().values(id='old-block',parse_run_id='old-parse',section_id='old-section',
                type='text',text='Existing evidence',reading_order=0,regions=[],source='old',quality_flags=[],data={}))
            c.execute(file_parse_heads.insert().values(paper_file_id='old-file',parse_run_id='old-parse'))
        retained=[t for t in old if t is not schema_migrations]
        before=read_legacy(target,retained)
        def fail(c):raise RuntimeError('v3 ddl fault')
        with pytest.raises(RuntimeError,match='v3 ddl'):migrate(target,after_ddl=fail)
        assert 'reading_runs' not in inspect(target).get_table_names()
        with target.connect() as c:assert c.exec_driver_sql('PRAGMA user_version').scalar()==2
        migrate(target);migrate(target)
        assert read_legacy(target,retained)==before
        assert {'reading_runs','reading_stages','reading_settings'}<=set(inspect(target).get_table_names())
    finally:target.dispose()

def test_v3_to_v4_preserves_reading_and_atomic_rollback(tmp_path):
    from backend.db import reading_runs,reading_stages,reading_settings,parse_runs
    target,legacy=v1_database(tmp_path)
    old=[t for t in meta.sorted_tables if not t.name.startswith('chat_')]
    try:
        meta.create_all(target,tables=old)
        with target.begin() as c:
            c.execute(schema_migrations.insert(),[{'version':v,'applied_at':v} for v in (1,2,3)])
            c.exec_driver_sql('PRAGMA user_version=3')
            c.execute(parse_runs.insert().values(id='parse',paper_file_id='old-file',job_id='old-job',file_sha256='a'*64,
                input_hash='b'*64,parser='native',parser_version='1',config_version='v3',config={},status='succeeded',created_at=1))
            c.execute(jobs.insert().values(id='read-job',type='read_paper',status='succeeded',payload={},attempts=1,
                max_attempts=3,available_at=1,created_at=1,updated_at=2))
            c.execute(reading_runs.insert().values(id='read',parse_run_id='parse',job_id='read-job',input_hash='c'*64,
                config={'evidence_contract':'source-fragments-2'},result={'important':'既有精读😀'},created_at=2))
            c.execute(reading_stages.insert().values(run_id='read',stage_key='original',result={'source':[{'text':'original'}]}))
            c.execute(reading_settings.insert().values(id='default',config={'model':'saved-local-config'}))
        retained=[t for t in old if t is not schema_migrations];before=read_legacy(target,retained)
        def fault(c):raise RuntimeError('v4 migration fault')
        with pytest.raises(RuntimeError,match='v4'):migrate(target,after_ddl=fault)
        assert 'chat_sessions' not in inspect(target).get_table_names()
        with target.connect() as c:assert c.exec_driver_sql('PRAGMA user_version').scalar()==3
        migrate(target);migrate(target)
        assert read_legacy(target,retained)==before
        assert {'chat_sessions','chat_messages','chat_turns','chat_events'}<=set(inspect(target).get_table_names())
    finally:target.dispose()
