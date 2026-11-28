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

app = FastAPI(title='PaperMind Workspace', version='0.2.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
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
        path_str = scope.get('path', '')
        if path_str == '/api' or path_str.startswith('/api/'):
            scope = {**scope, 'path': path_str[4:] or '/'}
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
from .highlights import router as highlights_router, delete_for_paper as delete_highlights_for_paper
app.include_router(highlights_router)
from .preferences import router as preferences_router
app.include_router(preferences_router)

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
        prows = [dict(r) for r in conn.execute(select(papers).order_by(papers.c.created_at.desc())).mappings()]
        if not prows:
            return []
        frows = conn.execute(select(
            paper_files.c.paper_id, paper_files.c.id, paper_files.c.version,
            paper_files.c.arxiv_version, paper_files.c.sha256, paper_files.c.source,
            paper_files.c.pages, paper_files.c.size, paper_files.c.created_at,
        ).order_by(paper_files.c.version.desc())).mappings().all()
    by_paper = {p['id']: [] for p in prows}
    for f in frows:
        d = dict(f)
        pid = d.pop('paper_id')
        if pid in by_paper:
            by_paper[pid].append(d)
    return [{**p, 'files': by_paper[p['id']]} for p in prows]

class PaperMetaInput(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    authors: list[str] | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1900, le=2100)

@app.patch('/papers/{pid}')
def update_paper(pid: str, body: PaperMetaInput):
    from .db import write_tx
    updates = {}
    if body.title is not None:
        updates['title'] = body.title.strip() or None
    if body.authors is not None:
        updates['authors'] = [a.strip() for a in body.authors if a.strip()] or None
    if body.year is not None:
        updates['year'] = body.year
    with write_tx() as conn:
        if not conn.execute(select(papers.c.id).where(papers.c.id == pid)).scalar():
            raise HTTPException(404, '论文不存在')
        if updates:
            conn.execute(papers.update().where(papers.c.id == pid).values(**updates))
        return paper_detail(pid, conn)

@app.delete('/papers/{pid}')
def delete_paper(pid: str):
    import shutil
    from .db import (write_tx, file_parse_heads, parse_runs, document_blocks, document_sections,
                     reading_runs, reading_stages, chat_sessions, chat_messages, chat_turns, chat_events,
                     notes, note_revisions, note_operations, note_reviews, note_exports,
                     glossary_versions, translation_runs, translation_blocks, translation_revisions,
                     translation_batches, translation_requests)
    with write_tx() as conn:
        if not conn.execute(select(papers.c.id).where(papers.c.id == pid)).scalar():
            raise HTTPException(404, '论文不存在')
        fids = conn.execute(select(paper_files.c.id).where(paper_files.c.paper_id == pid)).scalars().all()
        fpaths = conn.execute(select(paper_files.c.relative_path).where(paper_files.c.paper_id == pid)).scalars().all()
        prids = conn.execute(select(parse_runs.c.id).where(parse_runs.c.paper_file_id.in_(fids))).scalars().all() if fids else []
        nids = conn.execute(select(notes.c.id).where(notes.c.paper_id == pid)).scalars().all()
        if nids:
            nrids = conn.execute(select(note_revisions.c.id).where(note_revisions.c.note_id.in_(nids))).scalars().all()
            if nrids:
                conn.execute(note_reviews.delete().where(note_reviews.c.revision_id.in_(nrids)))
            conn.execute(note_exports.delete().where(note_exports.c.note_id.in_(nids)))
            conn.execute(note_operations.delete().where(note_operations.c.note_id.in_(nids)))
            conn.execute(note_revisions.delete().where(note_revisions.c.note_id.in_(nids)))
            conn.execute(notes.delete().where(notes.c.id.in_(nids)))
        sids = conn.execute(select(chat_sessions.c.id).where(chat_sessions.c.paper_id == pid)).scalars().all()
        if sids:
            tids = conn.execute(select(chat_turns.c.id).where(chat_turns.c.session_id.in_(sids))).scalars().all()
            if tids:
                conn.execute(chat_events.delete().where(chat_events.c.turn_id.in_(tids)))
                conn.execute(chat_turns.delete().where(chat_turns.c.id.in_(tids)))
            conn.execute(chat_messages.delete().where(chat_messages.c.session_id.in_(sids)))
            conn.execute(chat_sessions.delete().where(chat_sessions.c.id.in_(sids)))
        if prids:
            trids = conn.execute(select(translation_runs.c.id).where(translation_runs.c.parse_run_id.in_(prids))).scalars().all()
            if trids:
                conn.execute(translation_requests.delete().where(translation_requests.c.run_id.in_(trids)))
                conn.execute(translation_batches.delete().where(translation_batches.c.run_id.in_(trids)))
                conn.execute(translation_blocks.delete().where(translation_blocks.c.run_id.in_(trids)))
                conn.execute(translation_revisions.delete().where(translation_revisions.c.run_id.in_(trids)))
                conn.execute(translation_runs.delete().where(translation_runs.c.id.in_(trids)))
            rrids = conn.execute(select(reading_runs.c.id).where(reading_runs.c.parse_run_id.in_(prids))).scalars().all()
            if rrids:
                conn.execute(reading_stages.delete().where(reading_stages.c.run_id.in_(rrids)))
                conn.execute(reading_runs.delete().where(reading_runs.c.id.in_(rrids)))
            conn.execute(file_parse_heads.delete().where(file_parse_heads.c.paper_file_id.in_(fids)))
            conn.execute(document_blocks.delete().where(document_blocks.c.parse_run_id.in_(prids)))
            conn.execute(document_sections.delete().where(document_sections.c.parse_run_id.in_(prids)))
            conn.execute(parse_runs.delete().where(parse_runs.c.id.in_(prids)))
        conn.execute(glossary_versions.delete().where(glossary_versions.c.paper_id == pid))
        delete_highlights_for_paper(conn, pid)
        if fids:
            conn.execute(paper_files.delete().where(paper_files.c.id.in_(fids)))
        conn.execute(papers.delete().where(papers.c.id == pid))
    for rel in fpaths:
        try:
            file_path(rel).unlink(missing_ok=True)
        except OSError:
            pass
    for prid in prids:
        shutil.rmtree(STORAGE / 'parses' / prid, ignore_errors=True)
    return {'deleted': pid}

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


if os.getenv('PAPERMIND_SERVE_DIST') == '1':
    from fastapi.staticfiles import StaticFiles
    from .db import ROOT as _APP_ROOT
    _dist = _APP_ROOT / 'frontend' / 'dist'
    if _dist.is_dir():
        app.mount('/', StaticFiles(directory=str(_dist), html=True), name='frontend-dist')
