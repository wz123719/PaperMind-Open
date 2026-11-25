from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from . import translation as t
from .db import engine, translation_revisions, glossary_versions
from .llm_provider import probe_connection
from .reading_provider import ReadingFailure, validate_config

router = APIRouter(prefix='/v1', tags=['translation-v1'])


def invoke(fn, *args):
    try:
        return fn(*args)
    except t.Conflict as e:
        raise HTTPException(409, e.detail) from None
    except LookupError:
        raise HTTPException(404, '来源或运行不存在') from None
    except ValueError as e:
        raise HTTPException(409, str(e)[:300]) from None


class ModelInput(BaseModel):
    endpoint: str = Field(max_length=1000)
    model: str = Field(max_length=150)
    key_env: str = Field(default='', max_length=101)
    expected_revision: str | None = None
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    use_system_proxy: bool | None = None


class GlossaryInput(BaseModel):
    expected_revision: str | None = None
    entries: list[dict] = Field(max_length=500)


class RunInput(BaseModel):
    scope: str = 'full'
    ids: list[str] = Field(default_factory=list, max_length=3000)
    operation_key: str = Field(min_length=1, max_length=150)
    force: bool = False
    task: str = 'translation'


class EditInput(BaseModel):
    expected_revision: str
    text: str = Field(max_length=40000)


@router.get('/task-model-settings/{task}')
def settings(task: str):
    return invoke(t.settings, task)


@router.post('/task-model-settings/{task}')
def configure(task: str, body: ModelInput):
    return invoke(t.configure, task, body.model_dump(exclude_none=True))


@router.post('/task-model-settings/{task}/test')
def test_task_settings(task: str, body: ModelInput):
    def _probe():
        t.settings(task)
        cfg = validate_config(body.model_dump(exclude_none=True))
        return probe_connection(cfg, api_key_override=body.api_key, scope=task, failure_cls=ReadingFailure)
    return invoke(_probe)


@router.get('/papers/{pid}/glossary')
def glossary(pid: str):
    return invoke(t.glossary, pid)


@router.get('/papers/{pid}/glossary-versions')
def glossary_history(pid: str):
    with engine.connect() as c:
        return [dict(r) for r in c.execute(select(glossary_versions).where(glossary_versions.c.paper_id == pid).order_by(glossary_versions.c.created_at.desc())).mappings()]


@router.post('/papers/{pid}/glossary')
def save_glossary(pid: str, body: GlossaryInput):
    return invoke(t.save_glossary, pid, body.expected_revision, body.entries)


@router.post('/parse-runs/{pid}/translation-runs', status_code=202)
def submit(pid: str, body: RunInput):
    return invoke(t.submit, pid, body.scope, body.ids, body.operation_key, body.force, body.task)


@router.get('/parse-runs/{pid}/translation-runs')
def runs(pid: str):
    return invoke(t.list_runs, pid)


@router.get('/translation-runs/{rid}')
def run(rid: str):
    return invoke(t.get_run, rid)


@router.patch('/translation-runs/{rid}/blocks/{bid}')
def edit(rid: str, bid: str, body: EditInput):
    return invoke(t.edit, rid, bid, body.expected_revision, body.text)


@router.get('/translation-runs/{rid}/blocks/{bid}/revisions')
def history(rid: str, bid: str):
    invoke(t.get_run, rid)
    with engine.connect() as c:
        return [dict(r) for r in c.execute(select(translation_revisions).where(translation_revisions.c.run_id == rid, translation_revisions.c.block_id == bid).order_by(translation_revisions.c.created_at.desc())).mappings()]
