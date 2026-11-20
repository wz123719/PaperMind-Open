import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from backend import parsing,queue
from backend.db import engine,write_tx,jobs,parse_runs,paper_files,STORAGE
from backend.files import LeaseLost
from backend.worker import execute
from conftest import pdf_bytes

def uploaded(client,data=None):
    return client.post('/papers',files={'file':('parse.pdf',data or pdf_bytes(),'application/pdf')}).json()

def create(client,fid,**body):
    r=client.post('/v1/files/'+fid+'/parse-runs',json={'mode':'native',**body})
    assert r.status_code==202,r.text
    return r.json()

def run(created,worker='parser',converter=None):
    claimed=queue.claim(worker)
    assert claimed['id']==created['job_id']
    execute(claimed,worker,parse_converter=converter)
    return parsing.get_run(created['id'])

def test_native_parse_history_search_and_artifact_boundaries(client):
    f=uploaded(client)
    first=create(client,f['file_id']);assert 'artifact_root' not in first
    assert run(first)['status']=='succeeded'
    structure=client.get('/v1/parse-runs/'+first['id']+'/structure').json()
    assert structure['run']['parser']=='native' and structure['blocks']
    assert structure['run']['file_sha256']==f['paper']['files'][0]['sha256']
    assert all(b['source']=='pymupdf' and 'native_only'in b['quality_flags'] for b in structure['blocks'])
    assert 'PaperMind' in client.get('/v1/parse-runs/'+first['id']+'/markdown').text
    assert client.get('/v1/parse-runs/'+first['id']+'/assets/not-known.png').status_code==404
    search=client.get('/v1/files/'+f['file_id']+'/search',params={'q':'PaperMind'}).json()
    assert search['results'][0]['regions'][0]['page_index']==0
    assert all(0<=v<=1 for v in search['results'][0]['regions'][0]['bbox'])
    assert create(client,f['file_id'])['id']==first['id']
    second=create(client,f['file_id'],force=True)
    assert second['id']!=first['id']
    assert run(second)['status']=='succeeded'
    listed=client.get('/v1/files/'+f['file_id']+'/parse-runs').json()
    assert len(listed['runs'])==2 and listed['current_run_id']==second['id']
    assert client.get('/v1/parse-runs/'+first['id']+'/structure').json()==structure

def test_parse_failure_never_replaces_success_and_retry_is_bounded(client):
    f=uploaded(client);first=create(client,f['file_id']);run(first)
    old=client.get('/v1/parse-runs/'+first['id']+'/structure').json()
    new=create(client,f['file_id'],force=True)
    def broken(*args):
        (args[3]/'partial.md').write_text('unpublished partial result')
        raise parsing.ParseFailure('受控解析器故障')
    for n in range(3):
        end=run(new,converter=broken)
        assert end['status']==('queued' if n<2 else 'failed')
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==new['job_id']).values(available_at=0))
    assert '受控解析器故障' in end['error']
    assert client.get('/v1/parse-runs/'+new['id']+'/structure').status_code==409
    assert client.get('/v1/parse-runs/'+new['id']+'/markdown').status_code==409
    assert not list((STORAGE/'parses'/new['id']).glob('*/partial.md'))
    assert parsing.runs_for_file(f['file_id'])['current_run_id']==first['id']
    assert client.get('/v1/parse-runs/'+first['id']+'/structure').json()==old
    assert client.post('/jobs/'+new['job_id']+'/retry').status_code==202
    assert run(new)['status']=='succeeded'

def test_parse_duplicate_submission_concurrency(client):
    f=uploaded(client)
    with ThreadPoolExecutor(4) as pool:
        results=list(pool.map(lambda _:parsing.submit(f['file_id'],'native'),range(8)))
    assert len({r['id'] for r in results})==1
    assert sum(not r['reused'] for r in results)==1

def test_lease_loss_cannot_publish_and_recovers(client):
    f=uploaded(client);r=create(client,f['file_id'])
    job=queue.claim('stale')
    from backend.parse_pipeline import native_parse
    def expired(path,rid,config,work,report):
        result=native_parse(path,rid,config,work,report)
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(lease_expires_at=time.time()-1))
        return result
    execute(job,'stale',parse_converter=expired)
    assert parsing.get_run(r['id'])['artifact_root'] is None
    assert parsing.runs_for_file(f['file_id'])['current_run_id'] is None
    restarted=queue.claim('restarted');assert restarted['id']==job['id']
    execute(restarted,'restarted')
    assert parsing.get_run(r['id'])['status']=='succeeded'
    assert queue.get_job(job['id'])['attempts']==2

@pytest.mark.parametrize('scanned',[False,True])
def test_empty_scanned_pdf_explicit_native_warning(client,scanned):
    import pymupdf as fitz
    pdf=fitz.open();page=pdf.new_page()
    if scanned:
        source=fitz.open();source_page=source.new_page();source_page.insert_text((60,100),'Scanned text - native extraction is unavailable')
        page.insert_image(page.rect,stream=source_page.get_pixmap().tobytes('png'));source.close()
        assert page.get_images()
    raw=pdf.tobytes(deflate=True);pdf.close()
    f=uploaded(client,raw);r=create(client,f['file_id']);run(r)
    out=parsing.structure(r['id'])
    assert out['blocks']==[]
    assert any('OCR' in w for w in out['run']['warnings'])
    assert out['run']['parser']=='native'

def test_file_versions_and_configuration_runs_are_isolated(client):
    first=uploaded(client,pdf_bytes(title='Version A',doi='10.1234/parse'))
    second=uploaded(client,pdf_bytes(title='Version B',doi='10.1234/parse'))
    a=create(client,first['file_id']);run(a)
    assert parsing.runs_for_file(second['file_id'])['current_run_id'] is None
    b=create(client,second['file_id']);run(b)
    assert a['file_sha256']!=b['file_sha256'] and a['input_hash']!=b['input_hash']
    changed=create(client,second['file_id'],formulas=False)
    assert changed['id']!=b['id'] and changed['input_hash']!=b['input_hash']
    assert client.get('/v1/parse-runs/missing').status_code==404
    assert client.post('/v1/files/missing/parse-runs',json={}).status_code==404
    assert client.post('/v1/files/'+first['file_id']+'/parse-runs',json={'mode':'made-up'}).status_code==422

def test_older_run_finishing_later_does_not_replace_newer_head(client):
    f=uploaded(client)
    older=create(client,f['file_id']);old_job=queue.claim('older')
    newer=create(client,f['file_id'],force=True);run(newer,'newer')
    execute(old_job,'older')
    assert parsing.runs_for_file(f['file_id'])['current_run_id']==newer['id']
    assert parsing.get_run(older['id'])['status']=='succeeded'

def test_multiregion_block_survives_worker_publication_and_api(client):
    from backend.parse_pipeline import native_parse
    f=uploaded(client);created=create(client,f['file_id'])
    expected=[{'page_index':0,'bbox':[.1,.8,.4,.9]}, {'page_index':1,'bbox':[.1,.1,.4,.2]},
              {'page_index':1,'bbox':[.6,.1,.9,.2]}]
    def controlled(path,rid,config,work,report):
        output=native_parse(path,rid,config,work,report)
        output['blocks'][0]['regions']=expected
        output['blocks'][0]['quality_flags'].append('controlled_multiregion_geometry_fixture')
        return output
    assert run(created,converter=controlled)['status']=='succeeded'
    result=client.get('/v1/parse-runs/'+created['id']+'/structure').json()
    assert result['blocks'][0]['regions']==expected

def test_parse_actual_process_kill_then_restart(client,tmp_path):
    import os,subprocess,sys
    from backend.db import ROOT
    f=uploaded(client);created=create(client,f['file_id'])
    gate=tmp_path/'continue'
    env={**os.environ,'PYTHONPATH':str(ROOT)}
    def start(worker):
        return subprocess.Popen([sys.executable,str(ROOT/'tests/parse_worker_harness.py'),worker,str(gate)],
            cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    first=start('parse-before-kill');second=None
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and parsing.get_run(created['id'])['status']!='running':time.sleep(.05)
        assert parsing.get_run(created['id'])['status']=='running'
        assert parsing.runs_for_file(f['file_id'])['current_run_id'] is None
        first.kill();first.communicate(timeout=5)
        time.sleep(max(0,queue.get_job(created['job_id'])['lease_expires_at']-time.time())+.15)
        gate.touch();second=start('parse-after-restart')
        stdout,stderr=second.communicate(timeout=15)
        assert second.returncode==0,stderr
        assert parsing.get_run(created['id'])['status']=='succeeded'
        assert queue.get_job(created['job_id'])['attempts']==2
        assert parsing.runs_for_file(f['file_id'])['current_run_id']==created['id']
        assert len(parsing.runs_for_file(f['file_id'])['runs'])==1
        assert queue.events(created['job_id'])[-1]['type']=='succeeded'
    finally:
        for process in (first,second):
            if process is not None and process.poll() is None:
                process.kill();process.communicate(timeout=5)

def test_registered_asset_read_and_markdown_link(client):
    import pymupdf as fitz
    from backend.parse_pipeline import native_parse
    f=uploaded(client);created=create(client,f['file_id'])
    def extract(path,rid,config,work,report):
        output=native_parse(path,rid,config,work,report)
        with fitz.open(path) as pdf:pdf[0].get_pixmap().save(work/'source-region.png')
        output['blocks'][0]['data']['assets']=['source-region.png']
        return output
    assert run(created,converter=extract)['status']=='succeeded'
    prefix='/v1/parse-runs/'+created['id']
    response=client.get(prefix+'/assets/source-region.png')
    assert response.status_code==200 and response.content.startswith(b'\x89PNG')
    assert '(assets/source-region.png)' in client.get(prefix+'/markdown').text
    assert client.get(prefix+'/assets/document.md').status_code==404
    assert client.get(prefix+'/assets/unknown.png').status_code==404

def test_parser_version_change_requires_new_run(client,monkeypatch):
    f=uploaded(client);created=create(client,f['file_id'])
    monkeypatch.setattr(parsing,'parser_version',lambda _: 'changed-parser-version')
    end=run(created)
    assert end['status']=='queued' and '版本已变化' in end['error']
    assert parsing.runs_for_file(f['file_id'])['current_run_id'] is None

def test_mapping_configuration_change_requires_new_run(client,monkeypatch):
    f=uploaded(client);created=create(client,f['file_id'])
    monkeypatch.setattr(parsing,'CONFIG_VERSION','changed-config')
    end=run(created)
    assert end['status']=='queued' and '配置版本已变化' in end['error']
    assert parsing.runs_for_file(f['file_id'])['current_run_id'] is None

def test_third_party_parser_error_does_not_expose_internal_path(client):
    f=uploaded(client);created=create(client,f['file_id'])
    def unsafe(*args):raise ValueError('internal /example/local/storage/private-model secret-token')
    end=run(created,converter=unsafe)
    assert end['error']=='解析器执行失败，请查看本地 Worker 日志'
    body=client.get('/v1/parse-runs/'+created['id']).text
    assert '/example/local' not in body and 'secret-token' not in body

def test_explicit_compound_figure_retains_two_panels_without_guessing_unrelated_caption():
    from backend.parse_pipeline import make_block,link_compound_figures
    left=make_block('r',0,'picture','',[{'page_index':0,'bbox':[.1,.1,.3,.4]}],'docling',data={'caption':None,'assets':['left.png'],'docling_ref':'left'})
    right=make_block('r',1,'picture','',[{'page_index':0,'bbox':[.4,.1,.6,.4]}],'docling',data={'caption':'Figure 2: (left) attention. (right) multi-head.','assets':['right.png'],'docling_ref':'right'})
    unrelated=make_block('r',2,'picture','',[{'page_index':1,'bbox':[.1,.1,.3,.4]}],'docling',data={'caption':None,'assets':['other.png'],'docling_ref':'other'})
    link_compound_figures([left,right,unrelated])
    assert right['regions']==left['regions']+[{'page_index':0,'bbox':[.4,.1,.6,.4]}]
    assert set(right['data']['assets'])=={'left.png','right.png'}
    assert unrelated['data']['caption'] is None and len(unrelated['regions'])==1
    assert 'compound_figure_relation_candidate' in right['quality_flags']
