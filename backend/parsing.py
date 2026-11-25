"""Immutable parse runs; queue-backed publication fenced by the worker lease."""
import hashlib
import json
import os
import time
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
from sqlalchemy import select,func
from .db import (engine, write_tx, uid, jobs, emit, paper_files, parse_runs, STORAGE,
                 document_sections, document_blocks, file_parse_heads)
from .files import LeaseLost

CONFIG_VERSION = 'structure-v8-r4'
MODES = {'docling', 'native'}

ADAPTER_VERSION = 'structure-adapter-r5'

def adapter_hash():
    return hashlib.sha256(ADAPTER_VERSION.encode('utf-8')).hexdigest()

class ParseFailure(ValueError):
    """Known, safe-to-display parse failure; third-party exceptions stay in logs."""
    pass

def model_manifest_hash():
    manifest=STORAGE/'models'/'docling-cache'/'manifest.json'
    return hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None


def math_manifest_hash():
    manifest=STORAGE/'evaluation/rapid-models/manifest.json'
    return hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None

def parser_version(mode):
    try:
        return version('docling' if mode == 'docling' else 'PyMuPDF')
    except PackageNotFoundError:
        return 'unavailable'

def submit(fid, mode='docling', force=False, formulas=True, source_preferred=True):
    if mode not in MODES:
        raise ValueError('解析模式必须为 docling 或 native')
    config = {'mode': mode, 'formulas': formulas, 'ocr': False, 'tables': True,
              'coordinate_contract': 'normalized-unrotated-crop-topleft-v1'}
    limit=float(os.getenv('PAPERMIND_PARSE_TIMEOUT_SECONDS','1200'))
    if not 0<limit<=86400:raise ValueError('解析全流程硬超时必须在0至86400秒之间')
    if mode=='docling':config['wall_timeout_seconds']=limit
    if mode=='docling':
        rapid_ready = (STORAGE/'evaluation/latex-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')).is_file() and (STORAGE/'evaluation/rapid-models/manifest.json').is_file()
        backend_choice = 'pdf_math_layout+RapidLaTeXOCR' if rapid_ready and os.getenv('PAPERMIND_PREFER_RAPID_MATH')=='1' else 'CodeFormulaV2'
        config.update(formula_backend=backend_choice,formula_backend_version='2.0' if backend_choice=='CodeFormulaV2' else '0.0.9',
            math_manifest_sha256=math_manifest_hash() if (formulas and backend_choice!='CodeFormulaV2') else None,
            structure_refinement='r1',pdf_math_layout_version=2,
            math_selection='source_then_code_formula_v2' if backend_choice=='CodeFormulaV2' else 'supported_pdf_graph_else_image_candidate')
    if mode=='docling':
        from .source_files import registration
        from .mineru_math import manifest_hash
        config.update(object_router_version=5,pdf_math_layout_version=5,math_structure_version='math-tree-2',algorithm_layout_version=1,reading_layout_version=1,
                      source_preferred=source_preferred,source=registration(fid) if source_preferred else {'status':'disabled'},
                      table_refinement_version=4,source_table_alignment_version=1,mineru_math_manifest_sha256=manifest_hash() if formulas else None,
                      formula_route='source_candidate_then_supported_glyphs_then_mineru120_then_rapid60')
        config['adapter_sha256']=adapter_hash()
    math_manifest=STORAGE/'evaluation/rapid-models/manifest.json'
    if mode=='docling' and formulas and math_manifest.is_file():
        config['math_manifest']=json.loads(math_manifest.read_text(encoding='utf-8'))
        archive=STORAGE/'models/manifests'/('math-'+config['math_manifest_sha256']+'.json')
        archive.parent.mkdir(parents=True,exist_ok=True)
        if not archive.exists():archive.write_bytes(math_manifest.read_bytes())
    if mode=='docling':
        config['model_manifest_sha256']=model_manifest_hash()
        manifest=STORAGE/'models'/'docling-cache'/'manifest.json'
        if manifest.is_file():
            config['model_manifest']=json.loads(manifest.read_text(encoding='utf-8'))
    pv = parser_version(mode)
    with write_tx() as conn:
        file = conn.execute(select(paper_files).where(paper_files.c.id == fid)).mappings().first()
        if not file:
            raise LookupError('文件不存在')
        fingerprint = hashlib.sha256(json.dumps([file['sha256'], mode, pv, CONFIG_VERSION, config], sort_keys=True).encode()).hexdigest()
        if not force:
            old = conn.execute(select(parse_runs).where(parse_runs.c.paper_file_id == fid,
                parse_runs.c.input_hash == fingerprint, parse_runs.c.status.in_(['queued','running','succeeded']))
                .order_by(parse_runs.c.created_at.desc()).limit(1)).mappings().first()
            if old:
                return {**dict(old), 'reused': True}
        rid, jid, now = uid(), uid(), time.time()
        last_created=conn.execute(select(func.max(parse_runs.c.created_at)).where(parse_runs.c.paper_file_id==fid)).scalar()
        if last_created is not None:
            # Windows clock ticks (or clock adjustment) must not tie/reverse submission order.
            now=max(now,last_created+0.000001)
        conn.execute(jobs.insert().values(id=jid, type='parse_pdf', status='queued',
            payload={'parse_run_id': rid, 'paper_file_id': fid}, attempts=0, max_attempts=3,
            available_at=now, created_at=now, updated_at=now))
        conn.execute(parse_runs.insert().values(id=rid, paper_file_id=fid, job_id=jid,
            file_sha256=file['sha256'], input_hash=fingerprint, parser=mode, parser_version=pv,
            config_version=CONFIG_VERSION, config=config, status='queued', warnings=[], created_at=now))
        emit(conn, jid, 'queued', {'parse_run_id': rid, 'message': '等待结构解析'})
        result = dict(conn.execute(select(parse_runs).where(parse_runs.c.id == rid)).mappings().one())
        return {**result, 'reused': False}

def public_run(row):
    return {k: v for k, v in dict(row).items() if k != 'artifact_root'}

def get_run(rid):
    with engine.connect() as conn:
        row = conn.execute(select(parse_runs).where(parse_runs.c.id == rid)).mappings().first()
        return dict(row) if row else None

def runs_for_file(fid):
    with engine.connect() as conn:
        if not conn.execute(select(paper_files.c.id).where(paper_files.c.id == fid)).scalar():
            raise LookupError('文件不存在')
        rows = conn.execute(select(parse_runs).where(parse_runs.c.paper_file_id == fid)
                            .order_by(parse_runs.c.created_at.desc())).mappings().all()
        head = conn.execute(select(file_parse_heads.c.parse_run_id).where(file_parse_heads.c.paper_file_id == fid)).scalar()
        return {'runs': [public_run(r) for r in rows], 'current_run_id': head}

def structure(rid):
    run = get_run(rid)
    if not run:
        raise LookupError('解析运行不存在')
    if run['status'] != 'succeeded':
        raise ValueError('解析尚未完整成功，没有可发布的结构')
    with engine.connect() as conn:
        sections = [dict(r) for r in conn.execute(select(document_sections).where(document_sections.c.parse_run_id == rid)
                      .order_by(document_sections.c.reading_order)).mappings()]
        blocks = [dict(r) for r in conn.execute(select(document_blocks).where(document_blocks.c.parse_run_id == rid)
                    .order_by(document_blocks.c.reading_order)).mappings()]
    return {'run': public_run(run), 'sections': sections, 'blocks': blocks}

def assert_owned(conn, jid, worker):
    j = conn.execute(select(jobs).where(jobs.c.id == jid)).mappings().one()
    if j['status'] != 'running' or j['worker_id'] != worker or j['lease_expires_at'] <= time.time():
        raise LeaseLost('解析任务租约已失效')

def mark_running(rid, jid, worker):
    with write_tx() as conn:
        assert_owned(conn, jid, worker)
        conn.execute(parse_runs.update().where(parse_runs.c.id == rid).values(status='running', error=None))

def publish(rid, jid, worker, output, artifact_root, elapsed):
    """All structure + head + succeeded event commit together. No half publication."""
    now = time.time()
    with write_tx() as conn:
        assert_owned(conn, jid, worker)
        run = conn.execute(select(parse_runs).where(parse_runs.c.id == rid)).mappings().one()
        if run['status'] == 'succeeded':
            return
        for section in output['sections']:
            conn.execute(document_sections.insert().values(parse_run_id=rid, **section))
        for block in output['blocks']:
            conn.execute(document_blocks.insert().values(parse_run_id=rid, **block))
        conn.execute(parse_runs.update().where(parse_runs.c.id == rid).values(status='succeeded',
            warnings=output['warnings'], pages=output['pages'], artifact_root=artifact_root,
            elapsed_seconds=elapsed, error=None, completed_at=now))
        head = conn.execute(select(file_parse_heads).where(file_parse_heads.c.paper_file_id == run['paper_file_id'])).mappings().first()
        if not head:
            conn.execute(file_parse_heads.insert().values(paper_file_id=run['paper_file_id'], parse_run_id=rid))
        else:
            current_created = conn.execute(select(parse_runs.c.created_at).where(parse_runs.c.id == head['parse_run_id'])).scalar()
            if current_created <= run['created_at']:
                conn.execute(file_parse_heads.update().where(file_parse_heads.c.paper_file_id == run['paper_file_id']).values(parse_run_id=rid))
        result = {'parse_run_id': rid, 'paper_file_id': run['paper_file_id'], 'mode': run['parser'],
                  'blocks': len(output['blocks']), 'sections': len(output['sections'])}
        conn.execute(jobs.update().where(jobs.c.id == jid).values(status='succeeded', result=result,
            worker_id=None, lease_expires_at=None, error=None, updated_at=now))
        emit(conn, jid, 'succeeded', {'result': result, 'message': '结构解析完成（质量待核验）'})
