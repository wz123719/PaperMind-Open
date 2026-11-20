"""Controlled child for real process lifecycle tests, never a production converter."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from backend.process_guard import parent_pipe_guard

request=json.loads(sys.stdin.buffer.readline())
threading.Thread(target=parent_pipe_guard,daemon=True).start()
assert not sys.stdin.isatty()  # Windows CRT lock regression: guardian must not block this.
if request['stage']=='exit_without_complete':
    Path(request['partial']).write_text('INCOMPLETE')
    sys.exit(0)
grand=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
Path(request['pid_file']).write_text(json.dumps({'child':os.getpid(),'grandchild':grand.pid}))
print(json.dumps({'event':'progress','data':{'stage':request['stage'],'message':'阶段内处理中'}}),flush=True)
Path(request['partial']).write_text('PRIVATE INCOMPLETE')
while True:time.sleep(.05)
