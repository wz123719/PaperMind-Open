"""Real parse worker process; gated native parser used solely for recovery tests."""
import sys
import time
from pathlib import Path
from backend.db import init_db
from backend.queue import claim
from backend.worker import execute
from backend.parse_pipeline import native_parse

init_db()
worker,gate=sys.argv[1:]
job=claim(worker)
if job:
    def gated(path,rid,config,work,report):
        while not Path(gate).exists():time.sleep(.05)
        return native_parse(path,rid,config,work,report)
    execute(job,worker,parse_converter=gated)
