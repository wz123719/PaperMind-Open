import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from backend import queue, arxiv
from backend.db import engine, write_tx, jobs, emit
from backend.files import LeaseLost, save_pdf
from conftest import pdf_bytes
from backend.db import STORAGE

def new(): return queue.enqueue(arxiv.normalize('2301.12345v2'))

def expire(jid):
    with write_tx() as conn:
        conn.execute(jobs.update().where(jobs.c.id==jid).values(lease_expires_at=time.time()-1,available_at=0))

def test_competition_lease_fencing_and_recovery():
    jid=new()
    with ThreadPoolExecutor(2) as pool:
        claimed=list(pool.map(queue.claim, ['one','two']))
    assert sum(j is not None for j in claimed)==1
    winner=next(j for j in claimed if j)
    assert queue.heartbeat(jid,winner['worker_id'])
    expire(jid)
    replacement=queue.claim('replacement')
    assert replacement['id']==jid and replacement['attempts']==2
    assert not queue.heartbeat(jid,winner['worker_id'])
    with pytest.raises(LeaseLost): queue.finish(jid,winner['worker_id'],result={})
    p=STORAGE/'stale.part';p.write_bytes(pdf_bytes())
    with pytest.raises(LeaseLost): save_pdf(p,'upload',lease=(jid,winner['worker_id']))
    p.unlink()
    queue.finish(jid,'replacement',result={'recovered':True})
    assert queue.get_job(jid)['status']=='succeeded'

def test_retry_budget_and_manual_retry(client):
    jid=new()
    for n in range(3):
        job=queue.claim('w')
        assert job['attempts']==n+1
        queue.finish(jid,'w',error='controlled failure')
        with write_tx() as conn:
            conn.execute(jobs.update().where(jobs.c.id==jid).values(available_at=0))
    assert queue.get_job(jid)['status']=='failed'
    assert queue.claim('w') is None
    assert client.post('/jobs/'+jid+'/retry').status_code==202
    assert queue.claim('w')['attempts']==4
    assert client.post('/jobs/'+jid+'/retry').status_code==409
    assert client.post('/jobs/missing/retry').status_code==404

def test_expired_last_attempt_is_terminal():
    jid=new()
    for _ in range(3):
        assert queue.claim('w')
        expire(jid)
    assert queue.claim('other') is None
    assert queue.get_job(jid)['status']=='failed'
    assert queue.events(jid)[-1]['type']=='failed'

def test_crash_after_file_commit_before_job_finish():
    from backend.worker import execute
    jid=new();queue.claim('before-crash')
    p=STORAGE/'already-saved.part';data=pdf_bytes(arxiv='2301.12345v2');p.write_bytes(data)
    result=save_pdf(p,'arxiv:2301.12345v2',lease=(jid,'before-crash'))
    # The process disappeared here, with its file committed and job still running.
    expire(jid)
    recovered=queue.claim('after-crash')
    def downloader(payload,path,progress):
        path.write_bytes(data)
        return {**payload,'title':'Recovered fixture'}
    execute(recovered,'after-crash',downloader)
    end=queue.get_job(jid)
    assert end['status']=='succeeded'
    assert end['result']['duplicate'] and end['result']['file_id']==result['file_id']

def test_sse_terminal_replay_and_unknown(client):
    jid=new();queue.claim('w');queue.progress(jid,'w',{'bytes':123});queue.finish(jid,'w',result={'ok':True})
    events=queue.events(jid)
    response=client.get('/jobs/'+jid+'/events')
    assert response.status_code==200
    assert 'event: succeeded' in response.text
    assert response.text.count('id: ')==len(events)
    resumed=client.get('/jobs/'+jid+'/events',headers={'Last-Event-ID':str(events[1]['id'])})
    assert 'event: queued' not in resumed.text and 'event: running' not in resumed.text
    assert 'event: succeeded' in resumed.text
    assert client.get('/jobs/'+jid+'/events',headers={'Last-Event-ID':str(events[-1]['id'])}).text==''
    assert client.get('/jobs/'+jid+'/events',headers={'Last-Event-ID':'bad'}).status_code==400
    assert client.get('/jobs/missing/events').status_code==404

def test_actual_worker_process_kill_restart_and_competition(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    from backend.db import ROOT, paper_files
    from sqlalchemy import func
    jid=new()
    gate=tmp_path/'continue'
    pdf=tmp_path/'controlled.pdf';pdf.write_bytes(pdf_bytes())
    env={**os.environ,'PYTHONPATH':str(ROOT)}
    def start(name):
        return subprocess.Popen([sys.executable, str(ROOT/'tests/worker_harness.py'),name,str(gate),str(pdf)],
            cwd=ROOT, env=env, stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    first=start('process-first')
    second=None
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and queue.get_job(jid)['status']!='running': time.sleep(.05)
        assert queue.get_job(jid)['worker_id']=='process-first'
        second=start('process-competing')
        stdout,stderr=second.communicate(timeout=10)
        assert second.returncode==0 and '"claimed": null' in stdout, stderr
        # It remains owned across its initial lease thanks to the heartbeat thread.
        time.sleep(2.3)
        assert queue.get_job(jid)['lease_expires_at']>time.time()
        first.kill();first.communicate(timeout=5)
        expires=queue.get_job(jid)['lease_expires_at']
        time.sleep(max(0,expires-time.time())+.15)
        gate.touch()
        third=start('process-restarted')
        stdout,stderr=third.communicate(timeout=10)
        assert third.returncode==0, stderr
        job=queue.get_job(jid)
        assert job['status']=='succeeded' and job['attempts']==2
        # Execute a fresh import job for the same PDF after restart: still one blob/version.
        again=new();fourth=start('process-repeat')
        stdout,stderr=fourth.communicate(timeout=10)
        assert fourth.returncode==0 and queue.get_job(again)['result']['duplicate'],stderr
        with engine.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(paper_files))==1
    finally:
        for process in (first,second):
            if process and process.poll() is None:
                process.kill();process.communicate(timeout=5)
