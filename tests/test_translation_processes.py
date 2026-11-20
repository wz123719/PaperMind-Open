"""Actual API/Worker processes with independent environments; synthetic credentials only."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import httpx
import pytest
from conftest import pdf_bytes

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

@pytest.mark.parametrize('worker_has_credential',[True,False])
def test_translation_api_and_worker_independent_credential_environments(tmp_path,worker_has_credential):
    key_name='PAPERMIND_SYNTHETIC_PROCESS_KEY';synthetic='synthetic-process-test-value-only'
    seen=[]
    class Protocol(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append(self.headers.get('Authorization')=='Bearer '+synthetic)
            targets=json.loads(body['messages'][-1]['content'])['targets']
            output={'blocks':[{'source_block_id':t['source_block_id'],'text':'测试协议译文 '+''.join(__import__('re').findall(r'⟦PM:[^⟧]+⟧',t['text']))} for t in reversed(targets)]}
            data=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}],'usage':{'prompt_tokens':21,'completion_tokens':15}}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    model=ThreadingHTTPServer(('127.0.0.1',0),Protocol)
    threading.Thread(target=model.serve_forever,daemon=True).start()
    env=os.environ.copy();env.pop(key_name,None)
    env.update(PAPERMIND_STORAGE=str(tmp_path/'library'),PAPERMIND_MAX_BYTES='262144',PAPERMIND_LEASE_SECONDS='5',PYTHONIOENCODING='utf-8')
    root=Path(__file__).resolve().parents[1];api_port=port()
    api=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(api_port),'--no-access-log'],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    worker_env=env.copy()
    if worker_has_credential:worker_env[key_name]=synthetic
    worker=subprocess.Popen([sys.executable,'-m','backend.worker'],cwd=root,env=worker_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    def wait(fn,deadline=25):
        end=time.monotonic()+deadline
        while time.monotonic()<end:
            try:
                result=fn()
                if result:return result
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise AssertionError('Isolated process deadline exceeded')
    public=[]
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{api_port}',headers={'X-PaperMind-Client':'workspace'},trust_env=False,timeout=5) as client:
            wait(lambda:client.get('/health').status_code==200)
            f=client.post('/papers',files={'file':('fixture.pdf',pdf_bytes(),'application/pdf')}).json()
            p=client.post('/v1/files/'+f['file_id']+'/parse-runs',json={'mode':'native'}).json()
            wait(lambda:client.get('/v1/parse-runs/'+p['id']).json()['status']=='succeeded')
            config=client.post('/v1/task-model-settings/translation',json={'endpoint':f'http://127.0.0.1:{model.server_port}/chat','model':'protocol-only','key_env':key_name})
            assert config.status_code==200
            response=client.post('/v1/parse-runs/'+p['id']+'/translation-runs',json={'operation_key':'process-test'})
            assert response.status_code==202  # API has no key in BOTH cases
            r=response.json();public+=[response.text,config.text]
            target='succeeded' if worker_has_credential else 'failed'
            wait(lambda:client.get('/v1/translation-runs/'+r['id']).json()['status']==target)
            final=client.get('/v1/translation-runs/'+r['id']).json();public.append(json.dumps(final))
            if worker_has_credential:
                assert seen and all(seen)
                assert final['counts']['translated']==1 and final['counts']['completion']==1
                assert final['batches'][0]['data']['usage']['prompt_tokens']==21
                # SSE replays durable checkpoints, not just live notifications.
                stream=client.get('/jobs/'+r['job_id']+'/events')
                assert 'event: progress' in stream.text and 'event: succeeded' in stream.text
            else:
                assert not seen and final['attempts']==final['max_attempts']==3
                assert final['counts']['failed']==1
                assert '凭据环境变量未配置' in final['blocks'][0]['result']['reason']
            assert synthetic not in ''.join(public)
    finally:
        for proc in (worker,api):
            proc.terminate()
        for proc in (worker,api):
            try:output=proc.communicate(timeout=8)[0]
            except subprocess.TimeoutExpired:proc.kill();output=proc.communicate()[0]
            assert synthetic.encode() not in output
        model.shutdown();model.server_close()
    # All persisted rows/artifacts remain secret-free, including private stage cache.
    for path in (tmp_path/'library').rglob('*'):
        if path.is_file() and path.suffix not in ('.pdf',):assert synthetic.encode() not in path.read_bytes()
