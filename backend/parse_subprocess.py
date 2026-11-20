"""Worker owns lease/publication; child only produces complete private artifacts."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from .db import ROOT
from .parsing import ParseFailure
from .process_guard import start_owned,stop_owned


def run_conversion(request,report,*,timeout=None,command=None):
    limit=float(os.getenv('PAPERMIND_PARSE_TIMEOUT_SECONDS','1200')) if timeout is None else timeout
    if not 0<limit<=86400:raise ParseFailure('解析全流程硬超时配置必须在0至86400秒之间')
    started=time.monotonic();deadline=started+limit
    events=queue.Queue()
    proc,group=start_owned(command or [sys.executable,'-u','-m','backend.parse_child'],
        cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1'})
    def read():
        for line in proc.stdout:
            try:
                item=json.loads(line)
                if isinstance(item,dict):events.put(item)
            except (ValueError,UnicodeError):pass  # Third party stdout is never an API error.
    reader=threading.Thread(target=read,daemon=True);reader.start()
    stage='initializing';stage_start=started;last={};last_emit=0;complete=False;failure=None
    try:
        proc.stdin.write((json.dumps(request)+'\n').encode('utf-8'));proc.stdin.flush()
        while True:
            now=time.monotonic()
            if now>=deadline:raise ParseFailure(f'解析全流程超过{limit:g}秒，已终止子进程；旧成功结果保留')
            try:item=events.get(timeout=min(.1,max(.001,deadline-now)))
            except queue.Empty:item=None
            if item:
                if item.get('event')=='complete':complete=True
                elif item.get('event')=='failure':failure=item.get('safe_message')
                elif item.get('event')=='progress':
                    new=item.get('data',{})
                    if new.get('stage')!=stage:stage=new.get('stage',stage);stage_start=now
                    last=new;last_emit=0
            if now-last_emit>=5:
                report({**last,'stage':stage,'elapsed_seconds':round(now-started,1),
                    'stage_elapsed_seconds':round(now-stage_start,1),'child_pid':proc.pid,
                    'message':last.get('message','阶段内处理中')})
                last_emit=now
            if proc.poll() is not None:
                reader.join(timeout=2)
                while not events.empty():
                    item=events.get_nowait()
                    if item.get('event')=='complete':complete=True
                    if item.get('event')=='failure':failure=item.get('safe_message')
                if proc.returncode!=0 or not complete:raise ParseFailure(failure or '解析子进程失败，请查看本地Worker日志')
                return time.monotonic()-started
    finally:
        stop_owned(proc,group)
        if proc.stdin:proc.stdin.close()
        reader.join(timeout=3)
        if proc.stdout:proc.stdout.close()
