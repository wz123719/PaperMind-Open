from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from . import notes,note_exports

router=APIRouter(prefix='/v1',tags=['notes-v1'])
def invoke(fn,*args):
    try:return fn(*args)
    except notes.Conflict as e:raise HTTPException(409,e.detail) from e
    except LookupError as e:raise HTTPException(404,str(e)) from e
    except ValueError as e:raise HTTPException(409,str(e)) from e
    except OSError as e:raise HTTPException(409,'文件操作失败，已保留原文件；检查权限后重试发布记录') from e

class Create(BaseModel):
    paper_file_id:str
    parse_run_id:str|None=None
    reading_run_id:str|None=None
    title:str|None=Field(default=None,max_length=1000)
    operation_key:str=Field(min_length=8,max_length=100)
class Mutation(BaseModel):
    expected_revision:str
    operation_key:str=Field(min_length=8,max_length=100)
class Edit(Mutation):
    section_id:str
    markdown:str=Field(max_length=500000)
class Import(Mutation):
    reading_run_id:str
    section_ids:list[str]
class Answer(Mutation):
    section_id:str
    message_id:str
    mode:str='append'
class Restore(Mutation):
    revision_id:str
class Review(BaseModel):
    revision_id:str
    content_hash:str
class Vault(BaseModel):
    root:str=Field(max_length=1000)
    subdir:str=Field(max_length=180)
    expected_revision:str|None=None
class Preview(Review):
    operation_key:str=Field(min_length=8,max_length=100)
    fork:bool=False

@router.get('/notes')
def listing(paper_id:str|None=None):return invoke(notes.listing,paper_id)
@router.post('/notes',status_code=201)
def create(b:Create):return invoke(notes.create,b.paper_file_id,b.parse_run_id,b.reading_run_id,b.title,b.operation_key)
@router.get('/notes/{nid}')
def get(nid:str,revision_id:str|None=None):return invoke(notes.revision,nid,revision_id)
@router.get('/notes/{nid}/revisions')
def versions(nid:str):return invoke(notes.versions,nid)
@router.get('/notes/{nid}/diff')
def diff(nid:str,a:str,b:str):return invoke(notes.difference,nid,a,b)
@router.patch('/notes/{nid}/sections')
def edit(nid:str,b:Edit):return invoke(notes.edit,nid,b.expected_revision,b.operation_key,b.section_id,b.markdown)
@router.get('/notes/{nid}/reading-suggestions')
def suggestions(nid:str,reading_run_id:str):return invoke(notes.suggestions,nid,reading_run_id)
@router.post('/notes/{nid}/apply-reading')
def apply(nid:str,b:Import):return invoke(notes.apply_reading,nid,b.expected_revision,b.operation_key,b.reading_run_id,b.section_ids)
@router.get('/notes/{nid}/answer-preview')
def answer_preview(nid:str,message_id:str):return invoke(notes.answer_preview,nid,message_id)
@router.post('/notes/{nid}/answers')
def answer(nid:str,b:Answer):return invoke(notes.save_answer,nid,b.expected_revision,b.operation_key,b.section_id,b.message_id,b.mode)
@router.post('/notes/{nid}/restore')
def restore(nid:str,b:Restore):return invoke(notes.restore,nid,b.expected_revision,b.operation_key,b.revision_id)
@router.post('/notes/{nid}/review')
def review(nid:str,b:Review):return invoke(notes.review,nid,b.revision_id,b.content_hash)
@router.get('/notes/{nid}/assets')
def assets(nid:str):return invoke(notes.assets,nid)
@router.get('/notes/{nid}/evidence')
def evidence(nid:str,revision_id:str|None=None):
    rev=invoke(notes.revision,nid,revision_id)
    return {'identity':rev['snapshot']['identity'],'evidence':notes.evidence(rev['snapshot'])}
@router.get('/vault-settings')
def settings():return note_exports.settings()
@router.post('/vault-settings/validate')
def validate(b:Vault):return invoke(note_exports.validate,b.root,b.subdir)
@router.post('/vault-settings')
def configure(b:Vault):return invoke(note_exports.configure,b.root,b.subdir,b.expected_revision)
@router.post('/notes/{nid}/export-preview')
def preview(nid:str,b:Preview):return invoke(note_exports.preview,nid,b.revision_id,b.content_hash,b.operation_key,b.fork)
@router.get('/notes/{nid}/exports')
def export_history(nid:str):return invoke(note_exports.listing,nid)
@router.post('/note-exports/{eid}/commit')
def commit(eid:str):return invoke(note_exports.commit,eid)
@router.get('/note-exports/{eid}')
def result(eid:str):return invoke(note_exports.get,eid)
