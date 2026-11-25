from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import parsing
from .files import file_path
from threading import Lock

SEARCH_LOCK=Lock()  # PyMuPDF operations are serialized within the API process.

router=APIRouter(prefix='/v1',tags=['structure-v1'])

class ParseInput(BaseModel):
    mode: str='docling'
    force: bool=False
    formulas: bool=True
    source_preferred: bool=True

@router.post('/files/{fid}/parse-runs',status_code=202)
def create_parse(fid:str,body:ParseInput):
    try:
        return parsing.public_run(parsing.submit(fid,body.mode,body.force,body.formulas,body.source_preferred))
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc

@router.get('/files/{fid}/parse-runs')
def list_runs(fid:str):
    try:
        return parsing.runs_for_file(fid)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from exc

@router.get('/files/{fid}/source')
def source_status(fid:str):
    from .source_files import registration
    try:return registration(fid)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc

@router.post('/files/{fid}/source',status_code=202)
def source_download(fid:str):
    from .source_files import enqueue
    try:return {'job_id':enqueue(fid)}
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc

@router.get('/parse-runs/{rid}')
def get_run(rid:str):
    row=parsing.get_run(rid)
    if not row:
        raise HTTPException(404,'解析运行不存在')
    return parsing.public_run(row)

@router.get('/parse-runs/{rid}/structure')
def structure(rid:str):
    try:
        return parsing.structure(rid)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc

def artifact(rid,name,media):
    run=parsing.get_run(rid)
    if not run:
        raise HTTPException(404,'解析运行不存在')
    if run['status']!='succeeded' or not run['artifact_root']:
        raise HTTPException(409,'解析尚未完整成功')
    try:
        root=file_path(run['artifact_root'])
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(404,'解析资源不存在') from exc
    return FileResponse(path,media_type=media,headers={'X-Content-Type-Options':'nosniff'})

@router.get('/parse-runs/{rid}/markdown')
def markdown(rid:str):
    return artifact(rid,'document.md','text/markdown; charset=utf-8')

@router.get('/parse-runs/{rid}/json')
def json_document(rid:str):
    return artifact(rid,'structure.json','application/json')

from functools import lru_cache

@lru_cache(maxsize=128)
def _known_assets(rid: str) -> frozenset[str]:
    from sqlalchemy import select
    from .db import engine, document_blocks
    with engine.connect() as conn:
        rows = conn.execute(select(document_blocks.c.data).where(document_blocks.c.parse_run_id == rid)).scalars().all()
    return frozenset(a for d in rows if isinstance(d, dict) for a in d.get('assets', []))

@router.get('/parse-runs/{rid}/assets/{asset_id}')
def asset(rid:str,asset_id:str):
    row=parsing.get_run(rid)
    if not row:
        raise HTTPException(404,'解析运行不存在')
    if row['status']!='succeeded' or not row['artifact_root']:
        raise HTTPException(409,'解析尚未完整成功')
    if asset_id not in _known_assets(rid):
        raise HTTPException(404,'解析资源不存在')
    return artifact(rid,asset_id,'image/png')

@router.get('/files/{fid}/search')
def search(fid:str,q:str=Query(min_length=1,max_length=200)):
    import pymupdf as fitz
    from sqlalchemy import select
    from .db import engine,paper_files
    from .geometry import page_info,region
    with engine.connect() as conn:
        file=conn.execute(select(paper_files).where(paper_files.c.id==fid)).mappings().first()
    if not file:
        raise HTTPException(404,'文件不存在')
    results=[]
    with SEARCH_LOCK,fitz.open(file_path(file['relative_path'])) as pdf:
        for page in pdf:
            info=page_info(page)
            for rect in page.search_for(q):
                results.append({'text':page.get_textbox(rect), 'page_label':info['page_label'],
                    'regions':[region(page.number,list(rect),info['width_points'],info['height_points'])]})
                if len(results)>=200:
                    return {'results':results,'truncated':True,'mode':'native_text'}
    return {'results':results,'truncated':False,'mode':'native_text'}
