"""Unified workspace preferences & aggregated settings overview API."""
import importlib.util
import json
import os
import time
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .db import write_tx
from . import note_exports, reading, translation

router = APIRouter(prefix='/v1', tags=['preferences-v1'])

DEFAULT_PREFERENCES: dict = {
    'parse_mode': 'docling',
    'parse_formulas': True,
    'parse_source_preferred': True,
    'default_reader_mode': 'bilingual',
    'default_highlight_color': 'yellow',
    'default_bundle_pdf': False,
    'show_outline_by_default': True,
    'show_ai_panel_by_default': True,
}


def ensure_table(conn) -> None:
    conn.exec_driver_sql(
        '''CREATE TABLE IF NOT EXISTS workspace_preferences (
            id TEXT PRIMARY KEY,
            config TEXT NOT NULL,
            updated_at REAL NOT NULL
        )'''
    )


def capabilities() -> dict:
    docling_ok = importlib.util.find_spec('docling') is not None
    formula_backend = os.getenv('PAPERMIND_FORMULA_BACKEND', 'code_formula_v2')
    return {
        'docling_available': docling_ok,
        'formula_backend': formula_backend,
    }


def get_preferences() -> dict:
    with write_tx() as conn:
        ensure_table(conn)
        raw = conn.execute(
            text("SELECT config FROM workspace_preferences WHERE id = 'default'")
        ).scalar()
    saved = {}
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                saved = parsed
        except ValueError:
            saved = {}
    return {**DEFAULT_PREFERENCES, **{k: v for k, v in saved.items() if k in DEFAULT_PREFERENCES}}


def save_preferences(updates: dict) -> dict:
    current = get_preferences()
    merged = {**current}
    for k, v in updates.items():
        if k in DEFAULT_PREFERENCES and v is not None:
            merged[k] = v
    now = time.time()
    with write_tx() as conn:
        ensure_table(conn)
        conn.execute(text("DELETE FROM workspace_preferences WHERE id = 'default'"))
        conn.execute(
            text('INSERT INTO workspace_preferences (id, config, updated_at) VALUES (:id, :config, :updated_at)'),
            {'id': 'default', 'config': json.dumps(merged, ensure_ascii=False), 'updated_at': now},
        )
    return merged


def overview() -> dict:
    return {
        'preferences': get_preferences(),
        'llm': reading.public_settings(),
        'translation_model': translation.settings('translation'),
        'glossary_model': translation.settings('glossary'),
        'vault': note_exports.settings(),
        'capabilities': capabilities(),
    }


class PreferencesInput(BaseModel):
    parse_mode: Literal['docling', 'native'] | None = None
    parse_formulas: bool | None = None
    parse_source_preferred: bool | None = None
    default_reader_mode: Literal['bilingual', 'translation', 'original'] | None = None
    default_highlight_color: Literal['yellow', 'green', 'blue', 'pink'] | None = None
    default_bundle_pdf: bool | None = None
    show_outline_by_default: bool | None = None
    show_ai_panel_by_default: bool | None = None


@router.get('/workspace-preferences')
def api_get_preferences():
    return {**get_preferences(), 'capabilities': capabilities()}


@router.post('/workspace-preferences')
def api_save_preferences(body: PreferencesInput):
    try:
        saved = save_preferences(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**saved, 'capabilities': capabilities()}


@router.get('/settings-overview')
def api_settings_overview():
    return overview()
