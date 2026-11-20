"""Private subprocess entrypoint. Never commits database results or job status."""
import json
import logging
import sys
import threading
import traceback


def main():
    request=json.loads(sys.stdin.buffer.readline())
    from .process_guard import parent_pipe_guard
    threading.Thread(target=parent_pipe_guard,daemon=True).start()
    def send(event,**data):print(json.dumps({'event':event,**data},ensure_ascii=False),flush=True)
    send('progress',data={'stage':'initializing','message':'初始化解析模型：阶段内处理中'})
    from pathlib import Path
    from .parse_pipeline import docling_parse,write_artifacts
    from .parsing import ParseFailure
    try:
        output=docling_parse(Path(request['source']),request['rid'],request['config'],Path(request['work']),
            lambda data:send('progress',data=data))
        output.update(parse_run_id=request['rid'],file_sha256=request['file_sha256'])
        send('progress',data={'stage':'resources','message':'生成完整结构与资源：阶段内处理中'})
        write_artifacts(output,Path(request['work']))
        send('complete')
    except BaseException as exc:
        traceback.print_exc()
        send('failure',safe_message=str(exc)[:300] if isinstance(exc,ParseFailure) else '解析器执行失败，请查看本地Worker日志')
        return 1
    return 0

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
