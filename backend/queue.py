import time
from sqlalchemy import select, and_, or_
from .db import engine, jobs, job_events, parse_runs, uid, write_tx, emit, LEASE_SECONDS
from .files import LeaseLost

TERMINAL = {'succeeded', 'failed', 'cancelled'}
LANES = {
    'interactive': ('chat_answer', 'arxiv_import', 'arxiv_source'),
    'llm': ('read_paper', 'translate_paper'),
    'heavy': ('parse_pdf',),
}
JOB_LABELS = {
    'arxiv_import': '导入',
    'arxiv_source': '源码获取',
    'parse_pdf': '结构解析',
    'read_paper': '精读',
    'translate_paper': '学术翻译',
    'chat_answer': '问答',
}

def enqueue(payload):
    jid, now = uid(), time.time()
    with write_tx() as conn:
        conn.execute(jobs.insert().values(id=jid, type='arxiv_import', status='queued', payload=payload,
            attempts=0, max_attempts=3, available_at=now, created_at=now, updated_at=now))
        emit(conn, jid, 'queued', {'message': '等待 Worker 导入'})
    return jid

def get_job(jid):
    with engine.connect() as conn:
        j = conn.execute(select(jobs).where(jobs.c.id == jid)).mappings().first()
        return dict(j) if j else None

def claim(worker, job_types=None):
    now = time.time()
    with write_tx() as conn:
        expired = conn.execute(select(jobs).where(jobs.c.status == 'running', jobs.c.lease_expires_at <= now)).mappings().all()
        for j in expired:
            exhausted = j['attempts'] >= j['max_attempts']
            status = 'failed' if exhausted else 'queued'
            error = 'Worker 租约过期，已达到重试上限' if exhausted else 'Worker 中断，已重新排队'
            conn.execute(jobs.update().where(jobs.c.id == j['id']).values(status=status,
                worker_id=None, lease_expires_at=None, updated_at=now, available_at=now, error=error))
            conn.execute(parse_runs.update().where(parse_runs.c.job_id == j['id'], parse_runs.c.status != 'succeeded')
                         .values(status=status, error=error))
            if j['type']=='chat_answer':
                from .chat import failed
                failed(conn,j,status,error)
            emit(conn, j['id'], status, {'message': error, 'error': error})
        conds = [jobs.c.status == 'queued', jobs.c.available_at <= now, jobs.c.attempts < jobs.c.max_attempts]
        if job_types:
            conds.append(jobs.c.type.in_(tuple(job_types)))
        row = conn.execute(select(jobs).where(*conds).order_by(jobs.c.created_at).limit(1)).mappings().first()
        if not row:
            return None
        conn.execute(jobs.update().where(jobs.c.id == row['id']).values(status='running',
            worker_id=worker, attempts=row['attempts'] + 1, heartbeat_at=now,
            lease_expires_at=now + LEASE_SECONDS, updated_at=now, error=None))
        emit(conn, row['id'], 'running', {'attempt': row['attempts'] + 1, 'message':
            '正在精读' if row['type']=='read_paper' else '正在执行任务'})
        return dict(conn.execute(select(jobs).where(jobs.c.id == row['id'])).mappings().one())

def owned(jid, worker, now):
    return and_(jobs.c.id == jid, jobs.c.status == 'running', jobs.c.worker_id == worker,
                jobs.c.lease_expires_at > now)

def heartbeat(jid, worker):
    now = time.time()
    with write_tx() as conn:
        return conn.execute(jobs.update().where(owned(jid, worker, now)).values(
            heartbeat_at=now, lease_expires_at=now + LEASE_SECONDS, updated_at=now)).rowcount == 1

def progress(jid, worker, checkpoint):
    now = time.time()
    with write_tx() as conn:
        if not conn.execute(jobs.update().where(owned(jid, worker, now)).values(checkpoint=checkpoint, updated_at=now)).rowcount:
            raise LeaseLost('任务租约已失效')
        emit(conn, jid, 'progress', checkpoint)

def finish(jid, worker, result=None, error=None):
    now = time.time()
    with write_tx() as conn:
        j = conn.execute(select(jobs).where(owned(jid, worker, now))).mappings().first()
        if not j:
            raise LeaseLost('任务租约已失效')
        status = 'succeeded' if error is None else ('queued' if j['attempts'] < j['max_attempts'] else 'failed')
        conn.execute(jobs.update().where(jobs.c.id == jid).values(status=status, error=error, result=result,
            worker_id=None, lease_expires_at=None, available_at=now + min(30, 2 ** j['attempts']), updated_at=now))
        if j['type'] == 'parse_pdf' and error:
            conn.execute(parse_runs.update().where(parse_runs.c.job_id == jid, parse_runs.c.status != 'succeeded')
                         .values(status=status, error=error))
        if j['type']=='chat_answer' and error:
            from .chat import failed
            failed(conn,j,status,error)
        if error:
            emit(conn, jid, 'progress', {'error': error, 'message': '本次尝试失败'})
        label = JOB_LABELS.get(j['type'], '任务')
        emit(conn, jid, status, {'result': result, 'error': error, 'message':
             f'{label}完成' if status == 'succeeded' else ('稍后自动重试' if status == 'queued' else f'{label}失败')})

def retry(jid):
    with write_tx() as conn:
        j = conn.execute(select(jobs).where(jobs.c.id == jid)).mappings().first()
        if not j:
            raise LookupError('任务不存在')
        if j['status'] != 'failed':
            raise ValueError('只有失败任务可以手动重试')
        if j['type'] == 'read_paper' and j['payload'].get('pipeline_version') == 'knowledge_dimension_v1':
            raise ValueError('请使用精读专项重试入口')
        if j['type']=='chat_answer':
            from .chat import queue_retry
            queue_retry(conn,j)
        # Attempts count is lifetime total. Explicit retry grants another bounded budget.
        conn.execute(jobs.update().where(jobs.c.id == jid).values(status='queued',
            max_attempts=j['attempts'] + 3, available_at=time.time(), error=None, result=None, updated_at=time.time()))
        conn.execute(parse_runs.update().where(parse_runs.c.job_id == jid, parse_runs.c.status != 'succeeded')
                     .values(status='queued', error=None))
        emit(conn, jid, 'queued', {'message': '用户手动重试，新增三次尝试额度'})

def events(jid, after=0):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(job_events).where(job_events.c.job_id == jid,
            job_events.c.id > after).order_by(job_events.c.id)).mappings()]


def cancel_job(jid):
    now = time.time()
    with write_tx() as conn:
        j = conn.execute(select(jobs).where(jobs.c.id == jid)).mappings().first()
        if not j:
            raise LookupError('任务不存在')
        if j['status'] not in ('queued', 'running'):
            raise ValueError('只能取消等待或运行中的任务')
        label = JOB_LABELS.get(j['type'], '任务')
        conn.execute(jobs.update().where(jobs.c.id == jid).values(
            status='cancelled', worker_id=None, lease_expires_at=None, updated_at=now, error=None))
        if j['type'] == 'parse_pdf':
            conn.execute(parse_runs.update().where(parse_runs.c.job_id == jid, parse_runs.c.status != 'succeeded')
                         .values(status='cancelled', error='用户已取消解析'))
        if j['type'] == 'chat_answer':
            from .chat import failed
            failed(conn, j, 'failed', '用户已取消问答')
        emit(conn, jid, 'cancelled', {'message': f'{label}已取消'})
    return get_job(jid)

cancel_reading = cancel_job
