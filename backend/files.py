import hashlib
import re
import time
from pathlib import Path
from pypdf import PdfReader
from sqlalchemy import select, func
from .db import STORAGE, MAX_BYTES, paper_files, papers, jobs, uid, write_tx
from .arxiv import normalize

class LeaseLost(RuntimeError):
    pass

class IdentityConflict(ValueError):
    """Reliable identifiers disagree; no automatic merge or overwrite is safe."""
    pass

IDENTITY_FIELDS = ('doi', 'arxiv_id')
PAPER_FIELDS = ('title', 'authors', 'year', *IDENTITY_FIELDS)

def normalize_doi(value):
    return re.sub(r'^https://doi.org/', '', value.strip().lower()) if value else None

def check_identifiers(existing, incoming, fields):
    for key in fields:
        if existing[key] is not None and incoming.get(key) is not None and existing[key] != incoming[key]:
            raise IdentityConflict(f'论文身份冲突（{key}）：已有记录与本次信息不一致，需人工确认')

def enrich_paper(conn, paper, info):
    """Called inside BEGIN IMMEDIATE: check ownership before filling empty fields."""
    check_identifiers(paper, info, IDENTITY_FIELDS)
    for key in IDENTITY_FIELDS:
        if info.get(key):
            owner = conn.execute(select(papers.c.id).where(papers.c[key] == info[key])).scalar()
            if owner is not None and owner != paper['id']:
                raise IdentityConflict(f'论文身份冲突（{key}）：标识已归属其他论文，需人工确认')
    updates = {k: info[k] for k in PAPER_FIELDS if info.get(k) and not paper[k]}
    if updates:
        conn.execute(papers.update().where(papers.c.id == paper['id']).values(**updates))

def file_path(relative):
    p = (STORAGE / relative).resolve()
    if not p.is_relative_to(STORAGE) or p == STORAGE:
        raise ValueError('文件路径无效')
    return p

def inspect_pdf(path):
    size = path.stat().st_size
    if not size or size > MAX_BYTES:
        raise ValueError('PDF 为空或超过大小限制')
    with path.open('rb') as f:
        if f.read(5) != b'%PDF-':
            raise ValueError('文件不是有效 PDF')
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ValueError('本轮不支持加密 PDF')
        count = len(reader.pages)
        if not count:
            raise ValueError('PDF 没有页面')
        for page in reader.pages:
            _ = page.mediabox
        m = reader.metadata or {}
        info = {'title': str(m.get('/Title') or '').strip() or None,
                'authors': [str(m['/Author'])] if m.get('/Author') else None,
                'year': None, 'doi': None, 'arxiv_id': None, 'arxiv_version': None}
        # Only explicit identifier fields establish identity, never title similarity.
        doi = normalize_doi(str(m.get('/DOI') or ''))
        if doi and re.fullmatch(r'10\.\d{4,9}/\S+', doi):
            info['doi'] = doi
        if m.get('/arXivID'):
            try:
                info.update(normalize(str(m['/arXivID'])))
            except ValueError:
                pass
        return info, count, size
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF 结构损坏或无法打开') from exc

def save_pdf(path: Path, source: str, metadata=None, lease=None):
    """Hash-addressed rename + serialized identity/version allocation.

    A crash between rename and commit may leave an unreferenced blob. Retrying
    reuses that same path; it cannot create another version or duplicate blob.
    """
    info, pages, size = inspect_pdf(path)
    if metadata:
        metadata = dict(metadata)
        if metadata.get('doi'):
            metadata['doi'] = normalize_doi(metadata['doi'])
        # Do not let remote metadata silently replace explicit PDF identifiers.
        check_identifiers(info, metadata, (*IDENTITY_FIELDS, 'arxiv_version'))
        info.update({k: v for k, v in metadata.items() if k in info and v is not None})
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    with write_tx() as conn:
        if lease:
            j = conn.execute(select(jobs).where(jobs.c.id == lease[0])).mappings().one()
            if j['status'] != 'running' or j['worker_id'] != lease[1] or j['lease_expires_at'] <= time.time():
                raise LeaseLost('任务租约已失效')
        old = conn.execute(select(paper_files).where(paper_files.c.sha256 == digest)).mappings().first()
        if old:
            paper = conn.execute(select(papers).where(papers.c.id == old['paper_id'])).mappings().one()
            check_identifiers(old, info, ('arxiv_version',))
            enrich_paper(conn, paper, info)
            if old['arxiv_version'] is None and info['arxiv_version'] is not None:
                conn.execute(paper_files.update().where(paper_files.c.id == old['id']).values(
                    arxiv_version=info['arxiv_version']))
            # Identity enrichment never changes file ID, version, path or first source.
            return {'paper_id': old['paper_id'], 'file_id': old['id'], 'duplicate': True}
        by_arxiv = conn.execute(select(papers).where(papers.c.arxiv_id == info['arxiv_id'])).mappings().first() if info['arxiv_id'] else None
        by_doi = conn.execute(select(papers).where(papers.c.doi == info['doi'])).mappings().first() if info['doi'] else None
        if by_arxiv and by_doi and by_arxiv['id'] != by_doi['id']:
            raise IdentityConflict('论文身份冲突：arXiv 与 DOI 已归属不同论文，需人工确认')
        paper = by_arxiv or by_doi
        pid = paper['id'] if paper else uid()
        if not paper:
            conn.execute(papers.insert().values(id=pid, created_at=time.time(),
                         **{k: info[k] for k in PAPER_FIELDS}))
        else:
            enrich_paper(conn, paper, info)
        version = (conn.execute(select(func.max(paper_files.c.version)).where(paper_files.c.paper_id == pid)).scalar() or 0) + 1
        rel = f'pdf/{digest}.pdf'
        dest = file_path(rel)
        dest.parent.mkdir(exist_ok=True)
        path.replace(dest)
        fid = uid()
        conn.execute(paper_files.insert().values(id=fid, paper_id=pid, sha256=digest,
            version=version, arxiv_version=info['arxiv_version'], relative_path=rel,
            source=source, size=size, pages=pages, created_at=time.time()))
        return {'paper_id': pid, 'file_id': fid, 'duplicate': False}
