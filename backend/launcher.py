"""Run the local workspace under one foreground supervisor."""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener
import uuid
import webbrowser

from .process_guard import start_owned, stop_owned


ROOT = Path(__file__).resolve().parents[1]
HOST = '127.0.0.1'
HTTP = build_opener(ProxyHandler({}))
WORKER_WITH_ENV = ("from dotenv import load_dotenv; load_dotenv('.env', override=False); "
                   "import runpy; runpy.run_module('backend.worker', run_name='__main__')")


def available(port):
    with socket.socket() as probe:
        if os.name == 'nt':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((HOST, port))
        except OSError:
            raise RuntimeError(f'Port {port} is already in use. Stop the existing service or choose '
                               '-WebPort and -ApiPort.') from None


def http_ready(url):
    try:
        with HTTP.open(url, timeout=1.5) as response:
            return response.status == 200
    except OSError:
        return False


def wait_for(check, proc, label):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'{label} exited before startup.')
        if check():
            return
        time.sleep(.2)
    raise RuntimeError(f'{label} did not start in time.')


def launch(options):
    if options.web_port == options.api_port:
        raise RuntimeError('The web and API ports must be different.')
    for port in (options.web_port, options.api_port):
        available(port)
    web = f'http://{HOST}:{options.web_port}'
    api = f'http://{HOST}:{options.api_port}'
    logs = ROOT/'storage'/'runtime-logs'/('start-'+uuid.uuid4().hex)
    logs.mkdir(parents=True)
    print(f'Logs: {logs}', flush=True)
    origins = [web, f'http://localhost:{options.web_port}']
    origins.extend(x for x in os.getenv('PAPERMIND_ORIGINS', '').split(',') if x)
    env = dict(os.environ, PAPERMIND_ORIGINS=','.join(dict.fromkeys(origins)), PAPERMIND_VITE_API_URL=api)

    with ExitStack() as stack:
        def start(label, args, directory=ROOT):
            out = stack.enter_context((logs/f'{label}.out.txt').open('wb'))
            err = stack.enter_context((logs/f'{label}.err.txt').open('wb'))
            proc, job = start_owned(args, cwd=directory, env=env, stdout=out, stderr=err,
                                    stdin=subprocess.DEVNULL)
            stack.callback(stop_owned, proc, job)
            return proc

        server = start('api', [sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', HOST,
                               '--port', str(options.api_port), '--no-access-log'])
        wait_for(lambda: http_ready(api+'/health'), server, 'API')
        worker_args = ['-c', WORKER_WITH_ENV] if (ROOT/'.env').is_file() else ['-m', 'backend.worker']
        worker = start('worker', [sys.executable, *worker_args])
        wait_for(lambda: b' ready' in (logs/'worker.err.txt').read_bytes(), worker, 'Worker')
        frontend = start('web', [options.node, 'node_modules/vite/bin/vite.js', '--host', HOST,
                                  '--port', str(options.web_port), '--strictPort'], ROOT/'frontend')
        wait_for(lambda: http_ready(web+'/'), frontend, 'Web frontend')
        wait_for(lambda: http_ready(web+'/api/health'), frontend, 'API proxy')
        if worker.poll() is not None or server.poll() is not None:
            raise RuntimeError('A PaperMind service stopped during startup.')
        print(f'PaperMind: {web}/', flush=True)
        if options.check_only:
            return
        if not options.no_browser:
            try:
                webbrowser.open(web+'/')
            except (OSError, webbrowser.Error):
                print('A browser did not open automatically. Open the address above.', flush=True)
        print('Keep this window open. Press Ctrl+C to stop PaperMind.', flush=True)
        while True:
            if any(p.poll() is not None for p in (server, worker, frontend)):
                raise RuntimeError('A PaperMind service stopped. See the logs above.')
            time.sleep(.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-port', type=int, required=True)
    parser.add_argument('--api-port', type=int, required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    try:
        launch(parser.parse_args())
    except KeyboardInterrupt:
        print('PaperMind stopped.')
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'PaperMind: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
