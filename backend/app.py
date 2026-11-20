import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .db import STORAGE, MAX_BYTES, engine, papers, paper_files, jobs, init_db, uid
from .arxiv import normalize
from .files import save_pdf, file_path, IdentityConflict
from . import queue

ORIGINS = os.getenv('PAPERMIND_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173').split(',')

@asynccontextmanager
async def lifespan(_):
    init_db()
    yield

app = FastAPI(title='PaperMind Workspace', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=['GET', 'POST', 'PATCH'],
                   allow_headers=['Content-Type', 'X-PaperMind-Client', 'Last-Event-ID'])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])

class BodyTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, '请求超过大小限制')

class LocalGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        if scope['method'] not in ('GET', 'HEAD', 'OPTIONS'):
            origin = headers.get(b'origin', b'').decode()
            if (origin and origin not in ORIGINS) or headers.get(b'x-papermind-client') != b'workspace':
                return await JSONResponse({'detail': '本地来源校验失败'}, 403)(scope, receive, send)
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail': 'Content-Length 无效'}, 400)(scope, receive, send)
        limit = MAX_BYTES + 1024 * 1024
        if length > limit:
            return await JSONResponse({'detail': '请求超过大小限制'}, 413)(scope, receive, send)
        total = 0
        async def bounded():
            nonlocal total
            message = await receive()
            total += len(message.get('body', b''))
            if total > limit:
                raise BodyTooLarge()
            return message
        try:
            await self.app(scope, bounded, send)
        except BodyTooLarge:
            await JSONResponse({'detail': '请求超过大小限制'}, 413)(scope, receive, send)

app.add_middleware(LocalGuard)

from .parse_api import router as parse_router
app.include_router(parse_router)
from .reading_api import router as reading_router
app.include_router(reading_router)
from .chat_api import router as chat_router
app.include_router(chat_router)
from .notes_api import router as notes_router
app.include_router(notes_router)
from .translation_api import router as translation_router
app.include_router(translation_router)

def paper_detail(pid, conn):
    row = conn.execute(select(papers).where(papers.c.id == pid)).mappings().first()
    if not row:
        raise HTTPException(404, '论文不存在')
    result = dict(row)
    result['files'] = [dict(r) for r in conn.execute(select(paper_files.c.id, paper_files.c.version,
        paper_files.c.arxiv_version, paper_files.c.sha256, paper_files.c.source,
        paper_files.c.pages, paper_files.c.size, paper_files.c.created_at).where(
            paper_files.c.paper_id == pid).order_by(paper_files.c.version.desc())).mappings()]
    return result

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/papers')
def list_papers():
    with engine.connect() as conn:
        return [paper_detail(pid, conn) for pid in conn.execute(select(papers.c.id).order_by(papers.c.created_at.desc())).scalars()]

@app.get('/papers/{pid}')
def get_paper(pid: str):
    with engine.connect() as conn:
        return paper_detail(pid, conn)

@app.post('/papers', status_code=201)
def upload(file: UploadFile):
    temp_dir = STORAGE / 'tmp'
    temp_dir.mkdir(exist_ok=True)
    temp = temp_dir / (uid() + '.part')
    try:
        size = 0
        with temp.open('wb') as output:
            while chunk := file.file.read(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, 'PDF 超过大小限制')
                output.write(chunk)
        try:
            result = save_pdf(temp, 'upload')
        except IdentityConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with engine.connect() as conn:
            return {**result, 'paper': paper_detail(result['paper_id'], conn)}
    finally:
        temp.unlink(missing_ok=True)
        file.file.close()

class ImportInput(BaseModel):
    input: str = Field(min_length=1, max_length=300)

@app.post('/papers/imports', status_code=202)
def import_arxiv(body: ImportInput):
    try:
        payload = normalize(body.input)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'job_id': queue.enqueue(payload), **payload}

@app.get('/files/{fid}/content')
def content(fid: str):
    with engine.connect() as conn:
        record = conn.execute(select(paper_files).where(paper_files.c.id == fid)).mappings().first()
    if not record:
        raise HTTPException(404, '文件不存在')
    try:
        path = file_path(record['relative_path'])
    except ValueError as exc:
        raise HTTPException(404, '文件不可用') from exc
    if not path.is_file():
        raise HTTPException(404, '文件不可用')
    return FileResponse(path, media_type='application/pdf', filename=f'{fid}.pdf',
        content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff'})

@app.get('/jobs')
def list_jobs():
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(jobs).order_by(jobs.c.created_at.desc()).limit(100)).mappings()]

@app.get('/jobs/{jid}')
def get_job(jid: str):
    job = queue.get_job(jid)
    if not job:
        raise HTTPException(404, '任务不存在')
    return job

@app.post('/jobs/{jid}/retry', status_code=202)
def retry_job(jid: str):
    try:
        queue.retry(jid)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return queue.get_job(jid)

@app.post('/jobs/{jid}/cancel', status_code=202)
def cancel_reading(jid: str):
    try:
        return queue.cancel_reading(jid)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.get('/jobs/{jid}/events')
async def stream_events(jid: str, request: Request):
    if not queue.get_job(jid):
        raise HTTPException(404, '任务不存在')
    try:
        after = int(request.headers.get('last-event-id', '0'))
        if after < 0:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(400, 'Last-Event-ID 必须是非负整数') from exc
    async def stream():
        cursor, ping = after, time.monotonic()
        while not await request.is_disconnected():
            batch = await asyncio.to_thread(queue.events, jid, cursor)
            for e in batch:
                cursor = e['id']
                yield f"id: {cursor}\nevent: {e['type']}\ndata: {json.dumps(e['data'], ensure_ascii=False)}\n\n"
            # Read terminal state BEFORE a final event read, preventing a finish/read race.
            job = await asyncio.to_thread(queue.get_job, jid)
            if job['status'] in queue.TERMINAL:
                tail = await asyncio.to_thread(queue.events, jid, cursor)
                for e in tail:
                    cursor = e['id']
                    yield f"id: {cursor}\nevent: {e['type']}\ndata: {json.dumps(e['data'], ensure_ascii=False)}\n\n"
                return
            if time.monotonic() - ping >= 10:
                yield ': heartbeat\n\n'
                ping = time.monotonic()
            await asyncio.sleep(.5)
    return StreamingResponse(stream(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
