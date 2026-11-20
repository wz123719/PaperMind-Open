"""Optional isolated R2 math fallback, explicit network preparation only."""
import hashlib,json,os,subprocess,sys,venv
from pathlib import Path
root=Path(__file__).resolve().parent
storage=Path(os.getenv('PAPERMIND_STORAGE',str(root/'storage'))).resolve()
base=storage/'evaluation';envroot=base/'mineru-env';models=base/'mineru-models'
python=envroot/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
if not python.is_file():venv.EnvBuilder(with_pip=True).create(envroot)
subprocess.run([str(python),'-m','pip','install','-r',str(root/'backend/mineru-requirements.lock.txt')],check=True)
subprocess.run([str(python),'-m','pip','check'],check=True)
lock=(root/'backend/mineru-requirements.lock.txt').read_bytes();base.mkdir(parents=True,exist_ok=True)
(base/'mineru-runtime-lock.txt').write_bytes(lock)
env={**os.environ,'MINERU_HOME':str(models),'HF_HUB_DISABLE_XET':'1'}
tool=envroot/('Scripts/mineru-kit.exe' if os.name=='nt' else 'bin/mineru-kit')
for action in ['download','verify']:
    subprocess.run([str(tool),'models',action,'--tier','standard','--small-backend','onnx','--vlm-engine','llama-cpp'],env=env,check=True)
files=[]
for p in sorted(models.rglob('*')):
    if not p.is_file() or '.cache' in p.parts or p.suffix not in ('.onnx','.gguf','.json','.yaml','.txt','.model'):continue
    with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    files.append({'path':p.relative_to(storage).as_posix(),'bytes':p.stat().st_size,'sha256':digest})
if not any(p['path'].endswith('.gguf') for p in files):raise RuntimeError('No local GGUF model; manifest not published')
manifest={'component':'MinerU','package':'4.2.1','tier':'standard','transport':'local',
          'onnx_provider':'runtime-selected; inspect actual process log','runtime_lock_sha256':hashlib.sha256(lock).hexdigest(),'files':files}
target=base/'mineru-math-manifest.json';temp=target.with_suffix('.tmp')
temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,target)
print('Prepared optional math fallback:',target,'New model fingerprint requires a new parse run.')
