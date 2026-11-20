"""Real TCP provider streaming, API/Worker isolation, kill/recovery and persisted SSE."""
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
import psutil
import pytest
from conftest import pdf_bytes

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def kill_tree(proc):
    if proc.poll() is None:
        try:
            for p in psutil.Process(proc.pid).children(recursive=True):p.kill()
            proc.kill()
        except psutil.Error:pass
    return proc.communicate(timeout=8)[0]

@pytest.mark.parametrize('scenario',['stream','missing_key','kill_restart'])
def test_real_streaming_independent_processes_and_recovery(tmp_path,scenario):
    root=Path(__file__).resolve().parents[1];gate=threading.Event();calls=[];finished=[]
    synthetic='synthetic-chat-process-only';key_name='PAPERMIND_CHAT_PROCESS_KEY'
    class Protocol(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['stream'] is True
            calls.append(self.headers.get('Authorization')=='Bearer '+synthetic)
            source=json.loads(body['messages'][-1]['content'])['source'][0]
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            def frame(record):
                raw=('data: '+json.dumps({'choices':[{'delta':{'content':json.dumps(record,ensure_ascii=False)+'\n'}}]},ensure_ascii=False)+'\n\n').encode()
                for i in range(0,len(raw),3):self.wfile.write(raw[i:i+3])
                self.wfile.flush()
            try:
                frame({'type':'text','text':'协议测试😀首段。'})
                assert gate.wait(20)
                frame({'type':'text','text':'后续完成。'})
                frame({'type':'claim','claim':{'text':'protocol fact','kind':'fact','verification':'supported',
                    'evidence':[{'block_id':source['block_id'],'quote':source['text'][:25]}]}})
                frame({'type':'end'});self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush();finished.append(True)
            except (BrokenPipeError,ConnectionResetError):pass
    model=ThreadingHTTPServer(('127.0.0.1',0),Protocol);threading.Thread(target=model.serve_forever,daemon=True).start()
    env=os.environ.copy();env.pop(key_name,None)
    env.update(PAPERMIND_STORAGE=str(tmp_path/'library'),PAPERMIND_MAX_BYTES='262144',PAPERMIND_LEASE_SECONDS='2',PYTHONIOENCODING='utf-8')
    api_port=free_port();worker_env=env.copy()
    if scenario!='missing_key':worker_env[key_name]=synthetic
    processes=[]
    def launch_api():
        p=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(api_port),'--no-access-log'],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);processes.append(p);return p
    def launch_worker():
        p=subprocess.Popen([sys.executable,'-m','backend.worker'],cwd=root,env=worker_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);processes.append(p);return p
    api=launch_api();worker=launch_worker()
    def wait(fn):
        end=time.monotonic()+30
        while time.monotonic()<end:
            try:
                result=fn()
                if result:return result
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise AssertionError('chat process deadline')
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{api_port}',headers={'X-PaperMind-Client':'workspace'},trust_env=False,timeout=10) as c:
            wait(lambda:c.get('/health').status_code==200)
            f=c.post('/papers',files={'file':('fixture.pdf',pdf_bytes(),'application/pdf')}).json()
            p=c.post('/v1/files/'+f['file_id']+'/parse-runs',json={'mode':'native'}).json()
            wait(lambda:c.get('/v1/parse-runs/'+p['id']).json()['status']=='succeeded')
            c.post('/v1/reading-settings',json={'endpoint':f'http://127.0.0.1:{model.server_port}/chat','model':'protocol-test-only','key_env':key_name}).raise_for_status()
            sid=c.post('/v1/chat-sessions',json={'parse_run_id':p['id']}).json()['id']
            assert not calls  # Settings/session creation do not invoke a model.
            question={'question':'upload verification','idempotency_key':'process-key-000'}
            turn=c.post('/v1/chat-sessions/'+sid+'/messages',json=question)
            assert turn.status_code==202;turn=turn.json();tid=turn['id']
            assert c.post('/v1/chat-sessions/'+sid+'/messages',json=question).json()['id']==tid
            if scenario=='missing_key':
                wait(lambda:c.get('/v1/chat-turns/'+tid).json()['status']=='failed')
                final=c.get('/v1/chat-turns/'+tid).json()
                assert not calls and final['attempts']==3 and '凭据环境变量未配置' in final['error']
                assert c.get('/v1/chat-sessions/'+sid+'/messages').json()[-1]['status']=='failed'
            else:
                cursor=0;saw_delta=False
                with c.stream('GET','/v1/chat-turns/'+tid+'/events') as response:
                    kind=''
                    for line in response.iter_lines():
                        if line.startswith('id:'):cursor=int(line[3:])
                        if line.startswith('event:'):kind=line[6:].strip()
                        if line.startswith('data:') and kind=='delta':
                            assert json.loads(line[5:])['text']=='协议测试😀首段。';saw_delta=True;break
                assert saw_delta and not finished and not gate.is_set()  # genuine pre-completion network delta
                if scenario=='kill_restart':
                    kill_tree(worker);kill_tree(api);api=launch_api();worker=launch_worker()
                    wait(lambda:c.get('/health').status_code==200)
                    wait(lambda:c.get('/v1/chat-turns/'+tid).json()['attempts']==2)
                gate.set()
                replay=c.get('/v1/chat-turns/'+tid+'/events',headers={'Last-Event-ID':str(cursor)})
                assert 'event: completed' in replay.text
                final=c.get('/v1/chat-sessions/'+sid+'/messages').json()[-1]
                assert final['content']=='协议测试😀首段。后续完成。' and final['status']=='completed'
                if scenario=='kill_restart':assert c.get('/v1/chat-turns/'+tid).json()['attempts']==2
                assert calls and all(calls)
                assert final['data']['claims'][0]['verification']=='unreviewed'
                all_events=c.get('/v1/chat-turns/'+tid+'/events').text
                ids=[int(line[3:]) for line in all_events.splitlines() if line.startswith('id:')]
                assert ids==sorted(set(ids))
                assert c.get('/v1/chat-turns/'+tid+'/events',headers={'Last-Event-ID':str(ids[-1])}).text==''
            assert synthetic not in json.dumps(c.get('/v1/chat-turns/'+tid).json())
    finally:
        gate.set()
        for proc in processes:
            if proc.poll() is None:output=kill_tree(proc)
            else:output=proc.communicate()[0]
            assert synthetic.encode() not in output
        model.shutdown();model.server_close()
