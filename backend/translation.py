"""Immutable source/terminology snapshots, validated per-block checkpoints and lease fencing."""
import json
import re
import time
from pathlib import Path
from sqlalchemy import select
from .db import (engine, write_tx, uid, jobs, emit, paper_files, task_model_settings,
                 glossary_versions, translation_runs, translation_blocks, papers,
                 translation_revisions, translation_batches, translation_requests)
from . import parsing, queue
from .reading import digest, settings as workspace_model_settings
from .files import LeaseLost
from .reading_provider import validate_config, ReadingFailure
from .translation_provider import complete
from .translation_protection import protect, restore, normalize, VERSION

PROMPTS = Path(__file__).parent/'prompts'
DEFAULT_TERMS = [{'english':'neural network','chinese':'神经网络','priority':'default','locked':False}]
MAX_BLOCKS = 3000
MAX_INPUT = 10000
TRANSLATION_VERSION = 'translation-2-context'


class Conflict(ValueError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__('版本冲突，请保留编辑并人工合并')


def settings(task):
    from . import dpapi
    if task not in ('translation', 'glossary'):
        raise ValueError('任务类型无效')
    with engine.connect() as c:
        config = c.execute(select(task_model_settings.c.config).where(task_model_settings.c.id == task)).scalar()
    if config:
        return {**config, **dpapi.secret_metadata(task), 'source':'task'}
    workspace = workspace_model_settings()
    return {**workspace, **dpapi.secret_metadata(task), 'source':'workspace', 'workspace_revision':workspace['revision'], 'revision':None,
            'uses_default_model':workspace['revision'] is None}


def configure(task, value):
    from . import dpapi
    settings(task)  # Validate the task; the override revision is checked inside the transaction.
    config = validate_config(value)
    with write_tx() as c:
        current = c.execute(select(task_model_settings.c.config).where(task_model_settings.c.id == task)).scalar()
        if (current or {}).get('revision') != value.get('expected_revision'):
            raise Conflict({'remote':current})
        if value.get('clear_api_key'):
            dpapi.delete_secret(task)
        elif value.get('api_key') and str(value['api_key']).strip():
            dpapi.save_secret(task, str(value['api_key']))
        config['revision'] = uid()
        c.execute(task_model_settings.delete().where(task_model_settings.c.id == task))
        c.execute(task_model_settings.insert().values(id=task, config=config))
    return settings(task)


def glossary(paper_id):
    with engine.connect() as c:
        row = c.execute(select(glossary_versions).where(glossary_versions.c.paper_id == paper_id)
                        .order_by(glossary_versions.c.created_at.desc(), glossary_versions.c.id).limit(1)).mappings().first()
    return dict(row) if row else {'id':None,'paper_id':paper_id,'entries':[]}


def effective(entries):
    selected = {}
    for entry in DEFAULT_TERMS + entries:
        key = normalize(entry['english'])
        rank = 3 if entry.get('locked') else (2 if entry.get('priority') == 'confirmed' else (1 if entry.get('priority') == 'default' else 0))
        old = selected.get(key)
        if old and old[0] == rank and old[1]['chinese'] != entry['chinese']:
            raise ValueError('同一英文术语存在冲突译法：'+entry['english'])
        if not old or rank > old[0]:
            selected[key] = (rank, entry)
    return [row[1] for row in selected.values()]


def save_glossary(paper_id, expected, entries):
    if len(entries) > 500:
        raise ValueError('术语数超过500')
    clean = []
    for e in entries:
        if not isinstance(e,dict) or not isinstance(e.get('english'),str) or not isinstance(e.get('chinese'),str):
            raise ValueError('术语须包含英文和中文文本')
        english, chinese = e.get('english','').strip(), e.get('chinese','').strip()
        if not 1 <= len(english) <= 150 or not 1 <= len(chinese) <= 150 or any(ord(ch) < 32 for ch in english+chinese):
            raise ValueError('术语长度或字符无效')
        if e.get('priority') not in ('confirmed','suggested'):
            raise ValueError('术语优先级无效')
        clean.append({'english':english,'chinese':chinese,'priority':e['priority'],'locked':bool(e.get('locked'))})
    effective(clean)
    with write_tx() as c:
        if not c.execute(select(papers.c.id).where(papers.c.id==paper_id)).scalar():raise LookupError('论文不存在')
        current = c.execute(select(glossary_versions.c.id).where(glossary_versions.c.paper_id == paper_id)
                            .order_by(glossary_versions.c.created_at.desc(), glossary_versions.c.id).limit(1)).scalar()
        if current != expected:
            raise Conflict({'local':clean,'remote_revision':current})
        rid = uid()
        c.execute(glossary_versions.insert().values(id=rid,paper_id=paper_id,parent_id=current,entries=clean,created_at=time.time()))
    return glossary(paper_id)


def source(parse_id):
    doc = parsing.structure(parse_id)
    with engine.connect() as c:
        file = c.execute(select(paper_files).where(paper_files.c.id == doc['run']['paper_file_id'])).mappings().one()
    if file['sha256']!=doc['run']['file_sha256']:
        raise ValueError('PDF与解析来源哈希不匹配')
    return doc, dict(file)


def units(block):
    table = block.get('data',{}).get('table_model')
    if block['type'] == 'table':
        if not table or not table.get('cells'):
            return [], 'needs_review', 'table_without_structured_cells'
        return [{'id':f"{block['id']}/cell/{i}",'text':cell['text']} for i,cell in enumerate(table['cells']) if cell.get('text','').strip()], None, None
    if block['type'] in ('formula','equation','code','reference','references','bibliography','picture','figure','image'):
        return [], 'preserved', 'formula_code_reference_or_image_kept'
    if block['type'] not in ('text','paragraph','title','section_header','heading','caption','list_item','list','footnote','page_header','page_footer','algorithm_step'):
        return [], 'needs_review', 'unsupported_block_type'
    uncertain = set(block.get('quality_flags',[])) - {'native_only','reading_order_unverified','semantic_quality_unverified'}
    if uncertain or block['text'].count('$') % 2 or re.search(r'\\(?:frac|sum|begin)\b', block['text']) and '$' not in block['text']:
        return [], 'needs_review', 'uncertain_source_or_math_kept'
    if not block['text'].strip():
        return [], 'preserved', 'empty_source'
    return [{'id':block['id'],'text':block['text']}], None, None


def submit(parse_id, scope, ids, key, force=False, task='translation'):
    if task not in ('translation','glossary') or scope not in ('full','sections','blocks'):
        raise ValueError('翻译任务或范围无效')
    if not key or len(key)>150:
        raise ValueError('需要有效幂等键')
    request_hash = digest([parse_id,scope,sorted(set(ids)),force,task])
    with engine.connect() as c:
        existing = c.execute(select(translation_requests).where(translation_requests.c.key == key)).mappings().first()
    if existing:
        if existing['request_hash'] != request_hash:
            raise Conflict({'reason':'idempotency_key_reused'})
        return get_run(existing['run_id'])
    doc,file = source(parse_id)
    blocks = sorted(doc['blocks'],key=lambda b:b['reading_order'])
    all_blocks = blocks
    if scope != 'full':
        field = 'section_id' if scope == 'sections' else 'id'
        if not ids or set(ids)-{b[field] for b in blocks}:
            raise ValueError('范围ID不属于当前解析')
        blocks = [b for b in blocks if b[field] in ids]
    if not blocks or len(blocks)>MAX_BLOCKS:
        raise ValueError('没有来源块或超过3000块上限')
    selected_ids={b['id'] for b in blocks}
    saved = settings(task)
    if not saved['endpoint'] or not saved['model']:
        raise ReadingFailure('请先在工作台的 AI 分章节精读中配置默认模型，或为学术翻译单独指定模型')
    config = validate_config(saved)
    term = glossary(file['paper_id'])
    prompt = (PROMPTS/('translation.md' if task=='translation' else 'glossary.md')).read_text(encoding='utf-8')
    config = {**config,'settings_revision':saved.get('workspace_revision',saved['revision']),
              'source':saved['source'],'protocol':'chat-completions-json-1'}
    snapshot = {'paper_id':file['paper_id'],'paper_file_id':file['id'],'file_sha256':file['sha256'],
        'parse_run_id':parse_id,'parser_version':doc['run']['parser_version'],'blocks':blocks,
        'source_hash':digest(blocks),'glossary':term,'terms':effective(term['entries']), 'language':'zh-CN',
        'config':config,'prompt':prompt,'prompt_hash':digest(prompt),'protection':VERSION,
        'translation_version':TRANSLATION_VERSION,'force':force,'task':task,'scope':scope,
        'section_titles':{s['id']:s['title'] for s in doc['sections']},
        'contexts':{b['id']:[{'source_block_id':neighbor['id'],'parse_run_id':parse_id,
            'start':0,'end':min(400,len(neighbor['text'])),'text':neighbor['text'][:400]}
            for neighbor in all_blocks[max(0,i-1):i]+all_blocks[i+1:i+2]]
            for i,b in enumerate(all_blocks) if b['id'] in selected_ids},
        'budget':{'max_input_chars':MAX_INPUT,'max_output_chars':40000,'block_attempts':3,'max_calls':3000}}
    rid,jid,now = uid(),uid(),time.time()
    with write_tx() as c:
        other = c.execute(select(translation_requests).where(translation_requests.c.key == key)).mappings().first()
        if other:
            if other['request_hash'] != request_hash:raise Conflict({'reason':'idempotency_key_reused'})
            rid=other['run_id']
        else:
            active=c.execute(select(translation_runs).join(jobs,translation_runs.c.job_id==jobs.c.id).where(
                translation_runs.c.parse_run_id==parse_id,jobs.c.status.in_(['queued','running']))).mappings().all()
            same=next((r for r in active if digest(r['snapshot'])==digest(snapshot)),None)
            if same:rid=same['id']
            else:
                c.execute(jobs.insert().values(id=jid,type='translate_paper',status='queued',payload={'translation_run_id':rid},attempts=0,max_attempts=3,available_at=now,created_at=now,updated_at=now))
                c.execute(translation_runs.insert().values(id=rid,parse_run_id=parse_id,job_id=jid,request_key=key,request_hash=request_hash,snapshot=snapshot,created_at=now))
                emit(c,jid,'queued',{'message':'等待学术翻译Worker','total':len(blocks)})
            c.execute(translation_requests.insert().values(key=key,request_hash=request_hash,run_id=rid))
    return get_run(rid)


def get_run(rid):
    with engine.connect() as c:
        row = c.execute(select(translation_runs,jobs.c.status,jobs.c.error,jobs.c.attempts,jobs.c.max_attempts)
            .join(jobs,translation_runs.c.job_id==jobs.c.id).where(translation_runs.c.id==rid)).mappings().first()
        if not row:raise LookupError('翻译任务不存在')
        revisions = [dict(r) for r in c.execute(select(translation_revisions).join(translation_blocks,
            translation_revisions.c.id==translation_blocks.c.current_revision).where(translation_blocks.c.run_id==rid)).mappings()]
        batches = [dict(r) for r in c.execute(select(translation_batches).where(translation_batches.c.run_id==rid)).mappings()]
    result=dict(row);snap=result['snapshot']
    counts={s:sum(r['result']['status']==s for r in revisions) for s in ('translated','preserved','needs_review','failed')}
    result.update(blocks=revisions,batches=batches,counts={**counts,'total':len(snap['blocks']),
        'cache_hits':sum(bool(r['result'].get('cached')) for r in revisions),
        'completion':(counts['translated']+counts['preserved'])/len(snap['blocks'])})
    return result


def list_runs(parse_id):
    from sqlalchemy import func
    with engine.connect() as c:
        rows = c.execute(select(
            translation_runs.c.id, translation_runs.c.parse_run_id, translation_runs.c.job_id,
            translation_runs.c.request_key, translation_runs.c.request_hash, translation_runs.c.created_at,
            translation_runs.c.snapshot['scope'].as_string().label('scope'),
            translation_runs.c.snapshot['task'].as_string().label('task'),
            func.json_array_length(translation_runs.c.snapshot, '$.blocks').label('total_blocks'),
            jobs.c.status, jobs.c.error, jobs.c.attempts, jobs.c.max_attempts
        ).join(jobs, translation_runs.c.job_id == jobs.c.id)
         .where(translation_runs.c.parse_run_id == parse_id)
         .order_by(translation_runs.c.created_at.desc())).mappings().all()
        if not rows: return []
        rids = [r['id'] for r in rows]
        revs = c.execute(select(translation_blocks.c.run_id,
            translation_revisions.c.result['status'].as_string().label('s'),
            translation_revisions.c.result['cached'].as_boolean().label('c'))
            .join(translation_revisions, translation_revisions.c.id == translation_blocks.c.current_revision)
            .where(translation_blocks.c.run_id.in_(rids))).mappings().all()
    by_run = {k: [] for k in rids}
    for x in revs: by_run[x['run_id']].append(x)
    out = []
    for r in rows:
        d = dict(r); total = d.pop('total_blocks') or 1; rl = by_run[d['id']]
        counts = {s: sum(x['s'] == s for x in rl) for s in ('translated','preserved','needs_review','failed')}
        d['counts'] = {**counts, 'total': total, 'cache_hits': sum(bool(x['c']) for x in rl),
                       'completion': (counts['translated'] + counts['preserved']) / total}
        out.append(d)
    return out


def put_revision(c,rid,bid,result,parent=None,cache_key=None):
    revision=uid()
    c.execute(translation_revisions.insert().values(id=revision,run_id=rid,block_id=bid,parent_id=parent,cache_key=cache_key,result=result,created_at=time.time()))
    c.execute(translation_blocks.delete().where(translation_blocks.c.run_id==rid,translation_blocks.c.block_id==bid))
    c.execute(translation_blocks.insert().values(run_id=rid,block_id=bid,current_revision=revision))
    return revision


def edit(rid,bid,expected,text):
    run=get_run(rid)
    block=next((b for b in run['snapshot']['blocks'] if b['id']==bid),None)
    if not block:raise LookupError('来源块不存在')
    if block['type']=='table':raise ValueError('表格保留单元格结构，本阶段不支持整表手写')
    if not text.strip() or len(text)>40000:raise ValueError('编辑为空或超限')
    with write_tx() as c:
        head=c.execute(select(translation_revisions).join(translation_blocks,translation_blocks.c.current_revision==translation_revisions.c.id)
            .where(translation_blocks.c.run_id==rid,translation_blocks.c.block_id==bid)).mappings().first()
        if not head or head['id']!=expected:
            raise Conflict({'local':text,'remote':head['result']['text'] if head else None,'current_revision':head['id'] if head else None})
        result={**head['result'],'text':text,'status':'needs_review','manual':True,'validation':['manual_edit_unreviewed'],'cached':False}
        put_revision(c,rid,bid,result,expected)
    return get_run(rid)


def cache_key(snap,block):
    return digest({k:snap[k] for k in ('paper_id','paper_file_id','file_sha256','parse_run_id','parser_version','language','terms','glossary','config','prompt_hash','protection','translation_version','task')} | {'block':block,'context':snap['contexts'].get(block['id'],[]),'section_title':snap['section_titles'].get(block['section_id'],'')})


def validate_response(raw, targets):
    from .llm_provider import strip_json_fence
    try:
        rows=json.loads(strip_json_fence(raw))['blocks']
        if not isinstance(rows,list) or len(rows)!=len(targets):raise ValueError()
        ids=[r['source_block_id'] for r in rows]
        if len(set(ids))!=len(ids) or set(ids)!={t['id'] for t in targets}:raise ValueError()
        return {r['source_block_id']:restore(t['text'],t['protected'],r['text'],t['mapping'])
                for r in rows for t in targets if r['source_block_id']==t['id']}
    except (KeyError,TypeError,ValueError):
        raise ReadingFailure('返回ID、全文覆盖、保护元素或译文校验失败') from None


def glossary_response(raw,block):
    from .llm_provider import strip_json_fence
    try:
        terms=json.loads(strip_json_fence(raw))['terms']
        assert isinstance(terms,list) and len(terms)<=80
        result=[]
        for term in terms:
            en,zh=term['english'],term['chinese']
            assert term['source_block_id']==block['id'] and isinstance(en,str) and 1<=len(en)<=150 and en in block['text']
            assert isinstance(zh,str) and 1<=len(zh)<=150
            start=block['text'].index(en)
            result.append({'english':en,'chinese':zh,'source_block_id':block['id'],'start':start,'end':start+len(en),'status':'suggested','regions':block['regions']})
        return result
    except (KeyError,TypeError,ValueError,AssertionError):
        raise ReadingFailure('术语建议不在本次来源内或协议无效') from None


def _run_batch_groups(rid, snap, job, worker, cancelled, provider):
    if snap['task'] != 'translation' or len(snap['blocks']) < 2:
        return
    from .llm_provider import strip_json_fence
    with engine.connect() as c:
        done_ids = set(c.execute(select(translation_blocks.c.block_id).where(translation_blocks.c.run_id == rid)).scalars().all())
    group = []
    def flush(batch):
        if len(batch) < 2:
            return
        if cancelled():
            raise LeaseLost('翻译租约已失效')
        all_targets = []
        per_block = {}
        for b, ck, items in batch:
            tlist = []
            for item in items:
                protected, mapping = protect(item['text'], snap['terms'])
                tlist.append({**item, 'protected': protected, 'mapping': mapping})
            per_block[b['id']] = (b, ck, tlist)
            all_targets.extend(tlist)
        sec_id = batch[0][0]['section_id']
        payload = {'targets': [{'source_block_id': t['id'], 'text': t['protected']} for t in all_targets],
                   'section_id': sec_id, 'section_title': snap['section_titles'].get(sec_id, ''),
                   'task': 'translation', 'context': []}
        serialized = json.dumps(payload, ensure_ascii=False)
        if len(serialized) + len(snap['prompt']) > MAX_INPUT:
            return
        batchid = uid()
        start = time.monotonic()
        with write_tx() as c:
            if not c.execute(select(jobs.c.id).where(queue.owned(job['id'], worker, time.time()))).scalar():
                raise LeaseLost()
            c.execute(translation_batches.insert().values(
                id=batchid, run_id=rid,
                data={'block_id': 'batch:' + batch[0][0]['id'], 'state': 'started', 'input': payload, 'input_chars': len(serialized)},
                created_at=time.time()))
        raw = None; usage = None; error = None; per_results = {}
        try:
            raw, usage = provider(snap['config'], [{'role': 'system', 'content': snap['prompt']}, {'role': 'user', 'content': serialized}], cancelled)
            if not isinstance(raw, str) or len(raw) > 40000:
                raise ReadingFailure('输出超过限制')
            translated = validate_response(raw, all_targets)
            rows_by_id = {r['source_block_id']: r for r in json.loads(strip_json_fence(raw))['blocks']}
            for bid, (b, ck, tlist) in per_block.items():
                single_raw = json.dumps({'blocks': [rows_by_id[t['id']] for t in tlist]}, ensure_ascii=False)
                validate_response(single_raw, tlist)
                res = {'status': 'translated', 'reason': None, 'text': translated[bid], 'source_hash': digest(b),
                       'manual': False, 'cached': False, 'validation': ['deterministic_passed_semantics_unreviewed'],
                       'reviewed': False, 'validated_raw': single_raw, 'targets': tlist}
                res['cache_integrity'] = digest(res)
                per_results[bid] = (ck, res)
        except Exception as exc:
            if isinstance(exc, LeaseLost):
                raise
            error = str(exc)[:300]
        with write_tx() as c:
            if not c.execute(select(jobs.c.id).where(queue.owned(job['id'], worker, time.time()))).scalar():
                raise LeaseLost()
            c.execute(translation_batches.update().where(translation_batches.c.id == batchid).values(data={
                'block_id': 'batch:' + batch[0][0]['id'], 'state': 'failed' if error else 'validated',
                'input': payload, 'output': raw if isinstance(raw, str) and len(raw) <= 40000 else None,
                'usage': usage or 'unknown', 'cost': 'unknown', 'elapsed_seconds': time.monotonic() - start, 'error': error}))
            if not error:
                for bid, (ck, res) in per_results.items():
                    head = c.execute(select(translation_blocks.c.current_revision).where(
                        translation_blocks.c.run_id == rid, translation_blocks.c.block_id == bid)).scalar()
                    if not head:
                        put_revision(c, rid, bid, res, cache_key=ck)
                done = c.execute(select(translation_blocks.c.block_id).where(translation_blocks.c.run_id == rid)).scalars().all()
                checkpoint = {'stage': 'translation', 'processed': len(done), 'total': len(snap['blocks']), 'message': '已保存批量翻译检查点'}
                c.execute(jobs.update().where(queue.owned(job['id'], worker, time.time())).values(checkpoint=checkpoint, updated_at=time.time()))
                emit(c, job['id'], 'progress', checkpoint)

    for block in snap['blocks']:
        if block['id'] in done_ids or block['type'] == 'table':
            flush(group); group = []; continue
        ck = cache_key(snap, block); items, status, _ = units(block)
        if status is not None:
            flush(group); group = []; continue
        if not snap['force']:
            with engine.connect() as c:
                has_cache = c.execute(select(translation_revisions.c.id).where(translation_revisions.c.cache_key == ck).limit(1)).scalar()
            if has_cache:
                flush(group); group = []; continue
        if group and (group[-1][0]['section_id'] != block['section_id'] or len(group) >= 5
                      or sum(len(x[0]['text']) for x in group) + len(block['text']) > 3800):
            flush(group); group = []
        group.append((block, ck, items))
    flush(group)


def execute(job,worker,cancelled,provider=complete):
    rid=job['payload']['translation_run_id'];run=get_run(rid);snap=run['snapshot']
    if snap['protection']!=VERSION or snap['translation_version']!=TRANSLATION_VERSION:
        raise ReadingFailure('翻译保护协议已变更，请创建新任务；旧成果保持可读')
    _run_batch_groups(rid, snap, job, worker, cancelled, provider)
    for block in snap['blocks']:
        if cancelled():raise LeaseLost('翻译租约已失效')
        with engine.connect() as c:
            current=c.execute(select(translation_blocks.c.current_revision).where(
                translation_blocks.c.run_id==rid,translation_blocks.c.block_id==block['id'])).scalar()
        if current:continue  # including failed/exhausted blocks: bounded lifetime retry
        ck=cache_key(snap,block);items,status,reason=units(block)
        result={'status':status,'reason':reason,'text':block['text'],'source_hash':digest(block),
                'manual':False,'cached':False,'validation':[],'reviewed':False}
        cached=None
        if not snap['force']:
            with engine.connect() as c:
                candidates=c.execute(select(translation_revisions).where(translation_revisions.c.cache_key==ck).order_by(translation_revisions.c.created_at.desc())).mappings().all()
            for candidate in candidates:
                value=candidate['result']
                if value['status']=='translated' and not value.get('manual') and value.get('source_hash')==digest(block):
                    # Only accept cache whose restored response independently passes the current validator.
                    try:
                        if snap['task']=='glossary':glossary_response(value['validated_raw'],block)
                        else:validate_response(value['validated_raw'],value['targets'])
                        if value['cache_integrity'] != digest({k:v for k,v in value.items() if k != 'cache_integrity'} | {'cached':False}):continue
                    except (KeyError,ValueError):continue
                    cached={**value,'cached':True};break
        if cached:result=cached
        elif not status:
            attempts=0
            while attempts<3:
                with engine.connect() as c:
                    calls=c.execute(select(translation_batches.c.data['block_id'].as_string()).where(translation_batches.c.run_id==rid)).scalars().all()
                attempts=sum(b==block['id'] for b in calls)
                if attempts>=3 or len(calls)>=snap['budget']['max_calls']:
                    result.update(status='failed',reason='bounded_retry_or_call_budget_exhausted');break
                targets=[]
                for item in items:
                    protected,mapping=protect(item['text'],snap['terms'])
                    targets.append({**item,'protected':protected,'mapping':mapping})
                batchid=uid()
                payload={'targets':[{'source_block_id':t['id'],'text':t['protected']} for t in targets],
                         'section_id':block['section_id'],'section_title':snap['section_titles'].get(block['section_id'],''),
                         'task':snap['task'],'context':[]}
                for context in snap['contexts'].get(block['id'],[]):
                    protected_context,_=protect(context['text'],snap['terms'])
                    entry={**context,'text':protected_context,'context_only':True}
                    candidate={**payload,'context':payload['context']+[entry]}
                    if len(json.dumps(candidate,ensure_ascii=False))+len(snap['prompt'])<=MAX_INPUT:
                        payload=candidate
                if snap['task']=='glossary':payload={'source':[{'source_block_id':block['id'],'text':block['text']}]}
                serialized=json.dumps(payload,ensure_ascii=False)
                if len(serialized)+len(snap['prompt'])>MAX_INPUT:
                    result.update(status='needs_review',reason='block_exceeds_input_budget_no_truncation');break
                start=time.monotonic()
                # Reserve call before network I/O: crashes consume a bounded call budget.
                with write_tx() as c:
                    if not c.execute(select(jobs.c.id).where(queue.owned(job['id'],worker,time.time()))).scalar():raise LeaseLost()
                    c.execute(translation_batches.insert().values(id=batchid,run_id=rid,data={'block_id':block['id'],'state':'started','input':payload,'input_chars':len(serialized)},created_at=time.time()))
                raw=None;usage=None
                try:
                    raw,usage=provider(snap['config'],[{'role':'system','content':snap['prompt']},{'role':'user','content':serialized}],cancelled)
                    if not isinstance(raw,str) or len(raw)>40000:raise ReadingFailure('输出超过限制')
                    if snap['task']=='glossary':
                        result.update(status='translated',terms=glossary_response(raw,block),text=block['text'])
                    else:
                        translated=validate_response(raw,targets)
                        if block['type']=='table':
                            table=json.loads(json.dumps(block['data']['table_model']))
                            for i,cell in enumerate(table['cells']):
                                cell['text']=translated.get(f"{block['id']}/cell/{i}",cell['text'])
                            result.update(status='translated',table=table,text=block['text'])
                        else:result.update(status='translated',text=translated[block['id']])
                    result.update(reason=None,validation=['deterministic_passed_semantics_unreviewed'],validated_raw=raw,targets=targets)
                    result['cache_integrity']=digest(result)
                    error=None
                except ReadingFailure as exc:
                    error=str(exc)[:300]
                    result.update(status='failed',reason=error)
                with write_tx() as c:
                    if not c.execute(select(jobs.c.id).where(queue.owned(job['id'],worker,time.time()))).scalar():raise LeaseLost()
                    # The provider's arbitrary body is bounded and treated as data, never an error log.
                    c.execute(translation_batches.update().where(translation_batches.c.id==batchid).values(data={
                        'block_id':block['id'],'state':'failed' if error else 'validated','input':payload,
                        'output':raw if isinstance(raw,str) and len(raw)<=40000 else None,'usage':usage or 'unknown',
                        'cost':'unknown','elapsed_seconds':time.monotonic()-start,'error':error}))
                if not error:break
                attempts+=1
        with write_tx() as c:
            if not c.execute(select(jobs.c.id).where(queue.owned(job['id'],worker,time.time()))).scalar():raise LeaseLost()
            head=c.execute(select(translation_blocks.c.current_revision).where(translation_blocks.c.run_id==rid,translation_blocks.c.block_id==block['id'])).scalar()
            if not head:
                put_revision(c,rid,block['id'],result,cache_key=ck)
                done=c.execute(select(translation_blocks.c.block_id).where(translation_blocks.c.run_id==rid)).scalars().all()
                checkpoint={'stage':'translation','processed':len(done),'total':len(snap['blocks']),'message':'已保存块级检查点'}
                c.execute(jobs.update().where(queue.owned(job['id'],worker,time.time())).values(checkpoint=checkpoint,updated_at=time.time()))
                emit(c,job['id'],'progress',checkpoint)
    final=get_run(rid)
    queue.finish(job['id'],worker,result={'translation_run_id':rid,'counts':final['counts']},
                 error='存在翻译失败块，请查看逐块结果' if final['counts']['failed'] else None)
