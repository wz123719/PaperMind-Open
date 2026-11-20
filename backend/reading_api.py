from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from . import knowledge_reading, reading

router = APIRouter(prefix='/v1', tags=['reading-v1'])

class SettingsInput(BaseModel):
    endpoint: str = Field(max_length=1000)
    model: str = Field(max_length=150)
    key_env: str = Field(default='', max_length=101)

class ReadingBudget(BaseModel):
    max_input_tokens: int | None = Field(default=None, ge=256, le=1_000_000)
    max_output_tokens: int | None = Field(default=None, ge=256, le=1_000_000)
    max_total_tokens: int | None = Field(default=None, ge=512, le=1_000_000)

class ReadingInput(BaseModel):
    force: bool = False
    pipeline_version: Literal['section_v1', 'knowledge_dimension_v1'] | None = None
    language: Literal['zh-CN', 'en'] = 'zh-CN'
    reading_depth: Literal['deep'] = 'deep'
    use_cache: bool = True
    budget: ReadingBudget | None = None

def invoke(fn, *args):
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@router.get('/reading-settings')
def settings():
    return {**reading.public_settings(), 'knowledge_reading_enabled': knowledge_reading.enabled()}

@router.post('/reading-settings')
def configure(body: SettingsInput):
    return invoke(reading.configure, body.model_dump())

@router.post('/parse-runs/{rid}/reading-runs', status_code=202)
def create(rid: str, body: ReadingInput):
    # Existing clients without a pipeline version retain the original API contract.
    return reading.public_run(invoke(reading.submit, rid, body.force, body.model_dump()))

@router.get('/parse-runs/{rid}/reading-runs')
def runs(rid: str):
    return invoke(reading.list_runs, rid)

@router.get('/reading-runs/{rid}')
def run(rid: str):
    return reading.public_run(invoke(reading.get_run, rid))

@router.get('/reading-runs/{rid}/report')
def report(rid: str):
    return invoke(reading.report, rid)

@router.post('/reading-runs/{rid}/retry-specialties', status_code=202)
def retry_specialties(rid: str):
    return reading.public_run(invoke(reading.retry_specialties, rid))

@router.get('/reading-runs/{rid}/markdown')
def markdown(rid: str):
    report = invoke(reading.report, rid)
    if report.get('pipeline_version') != knowledge_reading.VERSION:
        raise HTTPException(409, '此入口只用于综合精读；旧报告可在笔记中保存')
    return {'markdown': knowledge_reading.MarkdownRenderer().render(report)}
