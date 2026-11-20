"""Official Hugging Face model download with bounded ranges and hash verification.

Alternative for unstable long CDN responses. Never disables TLS/hash checks and
never loads models or publishes a parse result. Uses only Docling's official repos.
"""
import hashlib
import json
import time
import os
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
from urllib.parse import quote
import httpx
from backend.db import STORAGE

ROOT=STORAGE/'models'/'docling-cache'/'models'
WORKERS=max(1,min(48,int(os.getenv('PAPERMIND_MODEL_DOWNLOAD_WORKERS','12'))))
ROOT.mkdir(parents=True,exist_ok=True)
CLIENT=httpx.Client(timeout=45,follow_redirects=True,limits=httpx.Limits(max_connections=12,max_keepalive_connections=12))
SPECS=[('ds4sd/docling-layout-heron','main',lambda f:f in ('model.safetensors','config.json','preprocessor_config.json')),
       ('ds4sd/docling-models','v2.3.0',lambda f:f.startswith('model_artifacts/tableformer/accurate/')),
       ('ds4sd/CodeFormulaV2','main',lambda f:f not in ('.gitattributes','README.md') and not f.endswith(('.png','.jpg','.md')))]

def get_json(url):
    for attempt in range(5):
        try:
            r=CLIENT.get(url);r.raise_for_status();return r.json()
        except httpx.HTTPError:
            if attempt==4:raise
            time.sleep(1)

def verified(path,item):
    if not path.is_file() or path.stat().st_size!=item['size']:return False
    if item.get('lfs'):
        expected=item['lfs']['sha256']
        with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()==expected
    data=path.read_bytes()
    return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()==item['blobId']

def fetch_file(repo,commit,item,folder):
    name=item['rfilename']
    dest=(folder/name).resolve()
    assert dest.is_relative_to(folder.resolve())
    dest.parent.mkdir(parents=True,exist_ok=True)
    if verified(dest,item):return
    url=f'https://huggingface.co/{repo}/resolve/{commit}/{quote(name)}?download=true'
    if item['size']<512*1024:
        for attempt in range(5):
            try:
                response=CLIENT.get(url);response.raise_for_status();dest.write_bytes(response.content)
                assert verified(dest,item),'Small file content hash mismatch'
                return
            except (httpx.HTTPError,AssertionError):
                if attempt==4:raise
        return
    chunkdir=STORAGE/'install'/'hf-chunks'/repo.replace('/','--')/name.replace('/','--')
    chunkdir.mkdir(parents=True,exist_ok=True)
    step=1024*1024;size=item['size']
    print('MODEL',repo,name,size,flush=True)
    def part(start):
        end=min(size-1,start+step-1);path=chunkdir/str(start)
        if path.is_file() and path.stat().st_size==end-start+1:return path
        for attempt in range(5):
            try:
                # A failed proxy stream must not poison a shared connection pool.
                with httpx.Client(timeout=45,follow_redirects=True) as local:
                    with local.stream('GET',url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'}) as r:
                        assert r.status_code==206,(r.status_code,'range unsupported')
                        total=0;started=time.monotonic()
                        with path.with_suffix('.part').open('wb') as f:
                            for chunk in r.iter_raw():
                                f.write(chunk);total+=len(chunk)
                                assert time.monotonic()-started<150,'Range total timeout'
                        assert total==end-start+1,'Range length mismatch'
                        path.with_suffix('.part').replace(path)
                if start%(16*step)==0:print('RANGE',repo,start,size,flush=True)
                return path
            except (httpx.HTTPError,AssertionError) as exc:
                print('RETRY',repo,start,attempt+1,type(exc).__name__,flush=True)
                if attempt==4:raise
                time.sleep(1)
    # Only schedule one window of work. A failing range must stop the batch instead
    # of leaving hundreds of already-enqueued requests running after the failure.
    starts=iter(range(0,size,step));completed={}
    with ThreadPoolExecutor(WORKERS) as pool:
        pending={pool.submit(part,s):s for s in [next(starts,None) for _ in range(WORKERS)] if s is not None}
        try:
            while pending:
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    start=pending.pop(future);completed[start]=future.result()
                    new=next(starts,None)
                    if new is not None:pending[pool.submit(part,new)]=new
        except BaseException:
            for future in pending:future.cancel()
            raise
    parts=[completed[s] for s in sorted(completed)]
    temp=dest.with_suffix('.download')
    with temp.open('wb') as f:
        for p in parts:f.write(p.read_bytes())
    assert verified(temp,item),'Complete model hash mismatch; not installing'
    temp.replace(dest)
    print('VERIFIED',repo,name,flush=True)

manifest=[]
try:
    for repo,revision,choose in SPECS:
        info=get_json(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true')
        folder=ROOT/repo.replace('/','--');folder.mkdir(exist_ok=True)
        selected=[s for s in info['siblings'] if choose(s['rfilename'])]
        print('REPOSITORY',repo,info['sha'],[(s['rfilename'],s['size']) for s in selected],flush=True)
        for item in selected:fetch_file(repo,info['sha'],item,folder)
        manifest.append({'repo':repo,'commit':info['sha'],'files':selected})
        (ROOT.parent/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('ALL OFFICIAL MODELS VERIFIED',flush=True)
finally:CLIENT.close()
