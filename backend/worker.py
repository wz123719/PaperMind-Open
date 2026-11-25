"""Run with python -m backend.worker, in a process separate from the API."""
import logging
import signal
import threading
import time
import httpx
from . import arxiv
from .db import STORAGE, LEASE_SECONDS, init_db, uid
from .files import save_pdf, LeaseLost
from .parsing import ParseFailure
from .queue import claim, heartbeat, progress, finish

log = logging.getLogger('papermind.worker')

def execute(job, worker, downloader=arxiv.download, parse_converter=None):
    stop = threading.Event()
    lost = threading.Event()
    def renew():
        while not stop.wait(max(.2, LEASE_SECONDS / 3)):
            try:
                if not heartbeat(job['id'], worker):
                    lost.set()
                    return
            except Exception:
                log.exception('Heartbeat failed')
                lost.set()
                return
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    temp_dir = STORAGE / 'tmp'
    temp_dir.mkdir(exist_ok=True)
    temp = temp_dir / f"{job['id']}-{worker}.part"
    last = [0.0]
    def report(total):
        if lost.is_set():
            raise LeaseLost('任务租约已失效')
        if time.monotonic() - last[0] > 1:
            progress(job['id'], worker, {'bytes': total, 'stage': 'download', 'message': f'已下载 {total} 字节'})
            last[0] = time.monotonic()
    try:
        if job['type']=='translate_paper':
            from .translation import execute as execute_translation
            execute_translation(job,worker,lost.is_set)
            return
        if job['type']=='chat_answer':
            from .chat import execute as execute_chat
            execute_chat(job,worker,lost.is_set)
            return
        if job['type'] == 'read_paper':
            from .reading import execute as execute_reading
            execute_reading(job, worker, lambda data: progress(job['id'], worker, data), lost.is_set)
            return
        if job['type'] == 'parse_pdf':
            from .parse_pipeline import execute_parse
            execute_parse(job, worker, lambda data: progress(job['id'], worker, data), parse_converter)
            return
        if job['type']=='arxiv_source':
            from .source_files import acquire,register
            fid=job['payload']['paper_file_id']
            metadata=acquire(fid,temp,report)
            result=register(fid,temp,metadata,lease=(job['id'],worker))
            finish(job['id'],worker,result=result)
            return
        if job['type'] != 'arxiv_import':
            raise ValueError('不支持的任务类型')
        metadata = downloader(job['payload'], temp, report)
        progress(job['id'], worker, {'stage': 'validate', 'message': '校验 PDF 并保存'})
        result = save_pdf(temp, 'arxiv:' + metadata['canonical'], metadata, (job['id'], worker))
        finish(job['id'], worker, result=result)
    except LeaseLost:
        log.warning('Lease lost for %s; stale worker cannot commit', job['id'])
    except Exception as exc:
        if job['type'] in ('read_paper','chat_answer','translate_paper'):
            from .reading_provider import ReadingFailure
            # Never log an arbitrary provider exception, URL, body or authorization header.
            log.warning('Reading attempt failed for %s (%s)', job['id'], type(exc).__name__)
            message = str(exc) if isinstance(exc, ReadingFailure) else '模型任务执行失败，请检查配置；未发布完整结果'
        else:
            log.exception('Import failed for %s', job['id'])
        if job['type'] in ('read_paper','chat_answer','translate_paper'):
            pass
        elif isinstance(exc, httpx.HTTPStatusError):
            message = f'arXiv 服务返回 HTTP {exc.response.status_code}'
        elif isinstance(exc, httpx.HTTPError):
            message = '无法连接 arXiv 或请求超时，请检查网络后重试'
        elif job['type']=='parse_pdf' and not isinstance(exc,ParseFailure):
            message = '解析器执行失败，请查看本地 Worker 日志'
        elif isinstance(exc, ValueError):
            message = str(exc)[:300]
        else:
            message = ('解析失败' if job['type']=='parse_pdf' else '导入失败')+'，请查看本地 Worker 日志'
        try:
            finish(job['id'], worker, error=message)
        except LeaseLost:
            pass
    finally:
        stop.set()
        thread.join(timeout=3)
        temp.unlink(missing_ok=True)

def main():
    from .queue import LANES
    logging.basicConfig(level=logging.INFO)
    init_db()
    worker = uid()
    shutdown = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: shutdown.set())
    signal.signal(signal.SIGTERM, lambda *_: shutdown.set())

    def run_lane(lane_name, job_types):
        lane_worker = f'{worker}:{lane_name}'
        while not shutdown.is_set():
            try:
                job = claim(lane_worker, job_types=job_types)
            except Exception:
                log.exception('Claim failed on lane %s', lane_name)
                shutdown.wait(1.0)
                continue
            if job:
                execute(job, lane_worker)
            else:
                shutdown.wait(.4)

    threads = [
        threading.Thread(target=run_lane, args=(name, types), name=f'worker-{name}', daemon=True)
        for name, types in LANES.items()
    ]
    for t in threads:
        t.start()
    log.info('Worker %s ready (lanes: %s)', worker, ','.join(LANES))
    while not shutdown.is_set():
        shutdown.wait(.5)
    for t in threads:
        t.join(timeout=5)

if __name__ == '__main__':
    main()
