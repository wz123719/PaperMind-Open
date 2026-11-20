"""Process-boundary test harness: real queue, lease thread, PDF save and DB.
Only remote arXiv responses use a clearly labelled controlled transport.
"""
import json
import sys
import time
from pathlib import Path
import httpx
from backend import queue, arxiv
from backend.db import init_db
from backend.worker import execute

init_db()
worker, gate, pdf = sys.argv[1:]
job = queue.claim(worker)
print(json.dumps({'claimed': job['id'] if job else None}), flush=True)
if job:
    def downloader(payload, path, progress):
        while not Path(gate).exists():
            time.sleep(.05)
        def respond(request):
            if request.url.host == 'export.arxiv.org':
                return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2301.12345v2</id><title>Process recovery fixture</title><published>2023-01-01T00:00:00Z</published></entry></feed>''')
            return httpx.Response(200,content=Path(pdf).read_bytes())
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            return arxiv.download(payload,path,progress,client)
    execute(job, worker, downloader)
