import asyncio
import json
import time
from fastapi import APIRouter,Request,HTTPException,Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from . import chat,chat_sources
from .reading_api import invoke

router=APIRouter(prefix='/v1',tags=['chat-v1'])
class SessionInput(BaseModel):
    parse_run_id:str
class QuestionInput(BaseModel):
    question:str=Field(min_length=1,max_length=4000)
    idempotency_key:str=Field(min_length=8,max_length=100)
    selection:dict|None=None
    reuse_selection_turn_id:str|None=None

@router.post('/chat-sessions',status_code=201)
def create(body:SessionInput):return invoke(chat.create_session,body.parse_run_id)
@router.get('/chat-sessions')
def sessions(paper_id:str):return chat.sessions(paper_id)
@router.get('/chat-sessions/{sid}')
def session(sid:str):return invoke(chat.session,sid)
@router.get('/chat-sessions/{sid}/messages')
def messages(sid:str):return invoke(chat.messages,sid)
@router.post('/parse-runs/{rid}/selection-map')
def selection_map(rid:str,body:dict):return invoke(chat_sources.map_selection,rid,body)
@router.post('/chat-sessions/{sid}/messages',status_code=202)
def submit(sid:str,body:QuestionInput):return invoke(chat.submit,sid,body.question,body.idempotency_key,body.selection,body.reuse_selection_turn_id)
@router.get('/chat-turns/{tid}')
def turn(tid:str):return invoke(chat.turn,tid)
@router.post('/chat-turns/{tid}/retry',status_code=202)
def retry(tid:str):
    from .queue import retry
    row=invoke(chat.turn,tid);invoke(retry,row['job_id']);return chat.turn(tid)

@router.get('/chat-turns/{tid}/events')
async def events(tid:str,request:Request,after:int=Query(default=0,ge=0)):
    invoke(chat.turn,tid)
    try:
        cursor=int(request.headers.get('last-event-id',str(after)))
        if cursor<0:raise ValueError()
    except ValueError:raise HTTPException(400,'Last-Event-ID须为非负整数') from None
    async def stream():
        last=cursor;ping=time.monotonic()
        while not await request.is_disconnected():
            batch=await asyncio.to_thread(chat.events,tid,last)
            for item in batch:
                last=item['id']
                yield f"id: {last}\nevent: {item['type']}\ndata: {json.dumps({'attempt':item['attempt'],**item['data']},ensure_ascii=False)}\n\n"
            current=await asyncio.to_thread(chat.turn,tid)
            if current['status'] in ('failed','succeeded'):
                tail=await asyncio.to_thread(chat.events,tid,last)
                if tail:continue
                return
            if time.monotonic()-ping>=10:yield ': heartbeat\n\n';ping=time.monotonic()
            await asyncio.sleep(.1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
