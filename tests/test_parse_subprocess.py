import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil
import pytest
from backend.files import LeaseLost
from backend.parsing import ParseFailure
from backend.parse_subprocess import run_conversion


def request(tmp_path,stage):
    return {'stage':stage,'pid_file':str(tmp_path/'pids.json'),'partial':str(tmp_path/'partial.json')}


def wait_file(path,timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if path.exists():return json.loads(path.read_text())
        time.sleep(.03)
    raise AssertionError('Child never started')


def assert_gone(pids):
    end=time.monotonic()+5
    while time.monotonic()<end:
        if not any(psutil.pid_exists(p) for p in pids):return
        time.sleep(.05)
    assert not [p for p in pids if psutil.pid_exists(p)]


@pytest.mark.parametrize('stage',['initializing','formula_enrichment','mapping','resources'])
def test_deadline_terminates_actual_child_and_descendant(tmp_path,stage):
    req=request(tmp_path,stage);seen=[]
    with pytest.raises(ParseFailure,match='全流程超过'):
        run_conversion(req,seen.append,timeout=2,command=[sys.executable,'-u','-m','tests.process_child_fixture'])
    pids=wait_file(tmp_path/'pids.json')
    assert_gone(pids.values())
    assert any(s['stage']==stage for s in seen)
    assert (tmp_path/'partial.json').exists()  # Private file never becomes a published result.


def test_lease_loss_terminates_actual_tree(tmp_path):
    req=request(tmp_path,'formula_enrichment')
    def lost(data):
        if data['stage']=='formula_enrichment':raise LeaseLost('lost')
    with pytest.raises(LeaseLost):
        run_conversion(req,lost,timeout=10,command=[sys.executable,'-u','-m','tests.process_child_fixture'])
    assert_gone(wait_file(tmp_path/'pids.json').values())


def test_zero_exit_without_complete_frame_is_not_success(tmp_path):
    with pytest.raises(ParseFailure,match='子进程失败'):
        run_conversion(request(tmp_path,'exit_without_complete'),lambda d:None,timeout=5,
            command=[sys.executable,'-u','-m','tests.process_child_fixture'])
    assert (tmp_path/'partial.json').read_text()=='INCOMPLETE'


def test_owner_force_kill_leaves_no_child_tree(tmp_path):
    req=request(tmp_path,'formula_enrichment')
    proc=subprocess.Popen([sys.executable,'-u','-m','tests.process_parent_fixture',json.dumps(req)],
        env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    try:
        pids=wait_file(tmp_path/'pids.json')
        # The venv stub is the OS parent, so kill its entire actual Python owner tree.
        descendants=psutil.Process(proc.pid).children(recursive=True)
        owner=next((p for p in descendants if 'tests.process_parent_fixture' in p.cmdline()),None)
        (owner or psutil.Process(proc.pid)).kill()
        proc.wait(timeout=10)
        assert_gone(pids.values())
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=5)


@pytest.mark.parametrize('stage',['initializing','formula_enrichment'])
def test_deadline_queue_budget_and_old_publication_boundary(client,tmp_path,monkeypatch,stage):
    from backend import parsing,queue
    from backend.db import write_tx,jobs
    from backend.worker import execute
    from conftest import pdf_bytes
    uploaded=client.post('/papers',files={'file':('p.pdf',pdf_bytes(),'application/pdf')}).json()
    old=parsing.submit(uploaded['file_id'],'native');execute(queue.claim('owner'),'owner')
    old_structure=parsing.structure(old['id'])
    new=parsing.submit(uploaded['file_id'],'docling')
    actual=run_conversion
    def stalled(req,report,**options):
        return actual({**req,**request(tmp_path,stage)},report,timeout=1.5,
            command=[sys.executable,'-u','-m','tests.process_child_fixture'])
    monkeypatch.setattr('backend.parse_subprocess.run_conversion',stalled)
    for attempt in range(3):
        job=queue.claim('owner');assert job['id']==new['job_id']
        execute(job,'owner')
        end=parsing.get_run(new['id'])
        assert end['status']==('failed' if attempt==2 else 'queued')
        assert end['artifact_root'] is None and '全流程超过' in end['error']
        assert_gone(wait_file(tmp_path/'pids.json').values())
        assert client.get('/v1/parse-runs/'+new['id']+'/structure').status_code==409
        assert client.get('/v1/parse-runs/'+new['id']+'/assets/partial.json').status_code==409
        assert parsing.runs_for_file(uploaded['file_id'])['current_run_id']==old['id']
        assert parsing.structure(old['id'])==old_structure
        with write_tx() as c:c.execute(jobs.update().where(jobs.c.id==job['id']).values(available_at=0))
    assert queue.claim('owner') is None
