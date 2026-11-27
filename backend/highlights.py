"""Persistent PDF sentence highlights and one-click insertion into knowledge notes."""
import json
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from .db import engine, paper_files, papers, uid, write_tx
from . import notes

ALLOWED_COLORS = {'yellow', 'green', 'blue', 'pink'}
router = APIRouter(prefix='/v1', tags=['highlights-v1'])


def ensure_table(conn) -> None:
    conn.exec_driver_sql(
        '''CREATE TABLE IF NOT EXISTS paper_highlights (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            paper_file_id TEXT NOT NULL,
            page_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT 'yellow',
            note TEXT NOT NULL DEFAULT '',
            regions TEXT NOT NULL,
            created_at REAL NOT NULL
        )'''
    )
    conn.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS ix_paper_highlights_file ON paper_highlights (paper_file_id, page_index)'
    )


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d['regions'] = json.loads(d['regions']) if isinstance(d['regions'], str) else d['regions']
    except ValueError:
        d['regions'] = []
    return d


def _validate_regions(regions: list[dict], page_index: int) -> list[dict]:
    clean = []
    for r in regions[:200]:
        if not isinstance(r, dict):
            continue
        bbox = r.get('bbox')
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            vals = [max(0.0, min(1.0, float(v))) for v in bbox]
        except (TypeError, ValueError):
            continue
        if vals[2] <= vals[0] or vals[3] <= vals[1]:
            continue
        pidx = r.get('page_index', page_index)
        clean.append({'page_index': int(pidx), 'bbox': vals})
    if not clean:
        raise ValueError('高亮区域坐标无效，请重新在 PDF 中划选句子')
    return clean


def list_for_file(fid: str) -> list[dict]:
    with write_tx() as conn:
        ensure_table(conn)
        if not conn.execute(select(paper_files.c.id).where(paper_files.c.id == fid)).scalar():
            raise LookupError('文件不存在')
        rows = conn.execute(
            text('SELECT * FROM paper_highlights WHERE paper_file_id = :fid ORDER BY page_index ASC, created_at ASC'),
            {'fid': fid},
        ).mappings().all()
    return [_row_to_dict(r) for r in rows]


def get_highlight(hid: str) -> dict:
    with write_tx() as conn:
        ensure_table(conn)
        row = conn.execute(text('SELECT * FROM paper_highlights WHERE id = :hid'), {'hid': hid}).mappings().first()
    if not row:
        raise LookupError('高亮记录不存在')
    return _row_to_dict(row)


def create_highlight(fid: str, page_index: int, excerpt: str, regions: list[dict], color: str = 'yellow', annotation: str = '') -> dict:
    clean_text = excerpt.strip()
    if not clean_text or len(clean_text) > 8000:
        raise ValueError('高亮文字不能为空或超过 8000 字符')
    if color not in ALLOWED_COLORS:
        raise ValueError('不支持的高亮颜色')
    clean_note = (annotation or '').strip()
    if len(clean_note) > 4000:
        raise ValueError('批注过长')
    clean_regions = _validate_regions(regions, page_index)
    hid = uid()
    now = time.time()
    with write_tx() as conn:
        ensure_table(conn)
        file_row = conn.execute(select(paper_files).where(paper_files.c.id == fid)).mappings().first()
        if not file_row:
            raise LookupError('文件不存在')
        if not 0 <= page_index < max(1, file_row['pages']):
            raise ValueError('页码超出 PDF 范围')
        conn.execute(
            text('''INSERT INTO paper_highlights
                (id, paper_id, paper_file_id, page_index, text, color, note, regions, created_at)
                VALUES (:id, :paper_id, :paper_file_id, :page_index, :text, :color, :note, :regions, :created_at)'''),
            {
                'id': hid,
                'paper_id': file_row['paper_id'],
                'paper_file_id': fid,
                'page_index': page_index,
                'text': clean_text,
                'color': color,
                'note': clean_note,
                'regions': json.dumps(clean_regions, ensure_ascii=False),
                'created_at': now,
            },
        )
    return get_highlight(hid)


def update_highlight(hid: str, *, color: str | None = None, annotation: str | None = None) -> dict:
    with write_tx() as conn:
        ensure_table(conn)
        row = conn.execute(text('SELECT * FROM paper_highlights WHERE id = :hid'), {'hid': hid}).mappings().first()
        if not row:
            raise LookupError('高亮记录不存在')
        new_color = row['color'] if color is None else color
        if new_color not in ALLOWED_COLORS:
            raise ValueError('不支持的高亮颜色')
        new_note = row['note'] if annotation is None else annotation.strip()
        if len(new_note) > 4000:
            raise ValueError('批注过长')
        conn.execute(
            text('UPDATE paper_highlights SET color = :color, note = :note WHERE id = :hid'),
            {'color': new_color, 'note': new_note, 'hid': hid},
        )
    return get_highlight(hid)


def delete_highlight(hid: str) -> dict:
    with write_tx() as conn:
        ensure_table(conn)
        res = conn.execute(text('DELETE FROM paper_highlights WHERE id = :hid'), {'hid': hid})
        if res.rowcount == 0:
            raise LookupError('高亮记录不存在')
    return {'deleted': hid}


def clear_for_file(fid: str) -> dict:
    with write_tx() as conn:
        ensure_table(conn)
        if not conn.execute(select(paper_files.c.id).where(paper_files.c.id == fid)).scalar():
            raise LookupError('文件不存在')
        res = conn.execute(text('DELETE FROM paper_highlights WHERE paper_file_id = :fid'), {'fid': fid})
    return {'deleted_count': res.rowcount}


def delete_for_paper(conn, paper_id: str) -> None:
    ensure_table(conn)
    conn.execute(text('DELETE FROM paper_highlights WHERE paper_id = :pid'), {'pid': paper_id})


def format_highlight_markdown(hl: dict) -> str:
    page_num = hl['page_index'] + 1
    quote_lines = ['> ' + ln for ln in hl['text'].splitlines() if ln.strip()]
    lines = [f'> [!quote] 原文高亮 · 第 {page_num} 页', *quote_lines]
    if hl.get('note'):
        lines.append('>')
        lines.append(f'> **批注**：{hl["note"]}')
    return '\n'.join(lines)


def save_highlights_to_note(
    highlight_ids: list[str],
    *,
    note_id: str | None = None,
    section_id: str | None = None,
    parse_run_id: str | None = None,
) -> dict:
    if not highlight_ids:
        raise ValueError('请至少选择一条高亮')
    items = [get_highlight(hid) for hid in dict.fromkeys(highlight_ids)]
    paper_id = items[0]['paper_id']
    file_id = items[0]['paper_file_id']
    if any(item['paper_id'] != paper_id for item in items):
        raise ValueError('一次只能将同一篇论文的高亮加入同一篇知识笔记')

    if note_id:
        rev = notes.revision(note_id)
        if rev['note']['paper_id'] != paper_id:
            raise ValueError('目标笔记不属于当前论文')
    else:
        existing = notes.listing(paper_id=paper_id)
        if existing:
            rev = notes.revision(existing[0]['id'])
        else:
            with engine.connect() as c:
                title = c.execute(select(papers.c.title).where(papers.c.id == paper_id)).scalar()
            rev = notes.create(
                file_id,
                parse_id=parse_run_id,
                title=title,
                key='hl-auto-' + uid()[:16],
            )

    sections = rev['snapshot']['sections']
    target_sid = section_id
    if not target_sid or not any(s['id'] == target_sid for s in sections):
        # Default to '个人疑问'/'关联笔记'/'参考资料' or last editable section, falling back to first
        preferred_ids = ('s11', 's12', 's05', 's02')
        target_sid = next((pid for pid in preferred_ids if any(s['id'] == pid for s in sections)), sections[-1]['id'])

    block_md = '\n\n'.join(format_highlight_markdown(hl) for hl in items)
    origins = [
        {
            'kind': 'highlight',
            'highlight_id': hl['id'],
            'source_version': 'pdf-highlight-v1',
            'page_index': hl['page_index'],
            'quote': hl['text'],
            'note': hl['note'],
            'regions': hl['regions'],
        }
        for hl in items
    ]

    def apply(snap):
        sec = notes.section(snap, target_sid)
        existing_md = (sec['markdown'] or '').strip()
        if existing_md in ('', '_待补充_', '_待手动添加关联笔记。_'):
            sec['markdown'] = block_md
        else:
            sec['markdown'] = existing_md + '\n\n' + block_md
        sec['origins'] = list(sec.get('origins') or []) + origins

    updated = notes.mutate(
        rev['note_id'],
        rev['id'],
        'hl-' + uid()[:24],
        'append_highlights',
        {'section_id': target_sid, 'highlight_ids': [h['id'] for h in items]},
        apply,
    )
    target_title = next((s['title'] for s in updated['snapshot']['sections'] if s['id'] == target_sid), target_sid)
    return {
        'note_id': updated['note_id'],
        'revision_id': updated['id'],
        'section_id': target_sid,
        'section_title': target_title,
        'count': len(items),
        'revision': updated,
    }


def _invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except notes.Conflict as exc:
        raise HTTPException(409, exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class HighlightCreate(BaseModel):
    page_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=8000)
    regions: list[dict] = Field(min_length=1, max_length=200)
    color: str = Field(default='yellow')
    note: str = Field(default='', max_length=4000)


class HighlightUpdate(BaseModel):
    color: str | None = None
    note: str | None = Field(default=None, max_length=4000)


class SaveHighlightsToNoteInput(BaseModel):
    highlight_ids: list[str] = Field(min_length=1, max_length=100)
    note_id: str | None = None
    section_id: str | None = None
    parse_run_id: str | None = None


@router.get('/files/{fid}/highlights')
def api_list_highlights(fid: str):
    return _invoke(list_for_file, fid)


@router.post('/files/{fid}/highlights', status_code=201)
def api_create_highlight(fid: str, body: HighlightCreate):
    return _invoke(create_highlight, fid, body.page_index, body.text, body.regions, body.color, body.note)


@router.patch('/highlights/{hid}')
def api_update_highlight(hid: str, body: HighlightUpdate):
    return _invoke(update_highlight, hid, color=body.color, annotation=body.note)


@router.delete('/highlights/{hid}')
def api_delete_highlight(hid: str):
    return _invoke(delete_highlight, hid)


@router.delete('/files/{fid}/highlights')
def api_clear_highlights(fid: str):
    return _invoke(clear_for_file, fid)


@router.post('/highlights/save-to-note')
def api_save_highlights_to_note(body: SaveHighlightsToNoteInput):
    return _invoke(
        save_highlights_to_note,
        body.highlight_ids,
        note_id=body.note_id,
        section_id=body.section_id,
        parse_run_id=body.parse_run_id,
    )
