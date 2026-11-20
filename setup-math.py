"""Prepare the isolated math runtime without downgrading production numpy."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import httpx

root=Path(__file__).resolve().parent;storage=Path(os.getenv('PAPERMIND_STORAGE',str(root/'storage')))
env=storage/'evaluation/latex-env';models=storage/'evaluation/rapid-models';models.mkdir(parents=True,exist_ok=True)
python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
if not python.is_file():subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
lock=root/'backend/math-runtime-requirements.lock.txt'
subprocess.run([str(python),'-m','pip','install','--index-url','https://pypi.org/simple','-r',str(lock)],check=True)
expected={
    'image_resizer.onnx':'e0b075c39700f64d50400f39c8fc186bbb3b5d84d31864008313f376603aca9d',
    'encoder.onnx':'01bf5dc25539ca0cd5b1bd29296ea495977a6ba5f629dc4178277809d26e5e7d',
    'decoder.onnx':'bd695497bf1b22279b7626f5916c79226e1e244c84355f8da7edfd2d921d0072',
    'tokenizer.json':'1dc27b18d6a518d0d5ff3f4bb7bd98521fe80ad39e5b2a246d4109f1bb9d5019'}
files=[]
for name,digest in expected.items():
    path=models/name;url='https://github.com/RapidAI/RapidLaTeXOCR/releases/download/v0.0.0/'+name
    if not path.is_file():
        temp=path.with_suffix(path.suffix+'.download')
        with httpx.stream('GET',url,follow_redirects=True,timeout=90) as response,temp.open('wb') as stream:
            response.raise_for_status()
            for chunk in response.iter_bytes(1024*256):stream.write(chunk)
        if hashlib.sha256(temp.read_bytes()).hexdigest()!=digest:raise ValueError('Model checksum mismatch: '+name)
        temp.replace(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    files.append({'file':name,'sha256':digest,'bytes':path.stat().st_size,'source':url})
code="import importlib.metadata,json;names=['rapid-latex-ocr','numpy','onnxruntime','pillow','opencv-python','tokenizers'];print(json.dumps({n:importlib.metadata.version(n) for n in names}))"
versions=json.loads(subprocess.check_output([str(python),'-c',code],text=True))
manifest={'component':'pdf_math_layout+RapidLaTeXOCR','runtime_packages':versions,'files':files,
    'requirements_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),
    'weight_provenance':'Official v0.0.0 release, locally pinned SHA256 from TLS-verified R1 evaluation; upstream digest unavailable'}
(models/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Isolated math runtime and all four pinned model hashes verified')
