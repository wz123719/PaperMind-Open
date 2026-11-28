"""Standalone Windows Desktop Launcher for non-CS researchers.

Serves compiled frontend/dist directly from FastAPI (no Node.js/Vite runtime required),
manages API + Multi-Lane Worker under Win32 Job Objects with zero black console windows,
and opens a chromeless native Edge/WebView2 Desktop App Window.
"""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
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
WORKER_WITH_ENV = (
    "from dotenv import load_dotenv; load_dotenv('.env', override=False); "
    "import runpy; runpy.run_module('backend.worker', run_name='__main__')"
)


def pick_port(preferred: int = 8765) -> int:
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if os.name == 'nt':
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                s.bind((HOST, candidate))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError('无法分配可用的本地端口')


def prune_old_logs(log_root: Path, keep: int = 10) -> None:
    if not log_root.is_dir():
        return
    dirs = sorted([p for p in log_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    for old in dirs[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def http_ready(url: str) -> bool:
    try:
        with HTTP.open(url, timeout=1.5) as resp:
            return resp.status == 200
    except OSError:
        return False


def wait_for(check, proc, label: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'{label} 启动前异常退出，请查看日志')
        if check():
            return
        time.sleep(0.2)
    raise RuntimeError(f'{label} 启动超时')


def find_edge_binary() -> str | None:
    if os.name != 'nt':
        return None
    candidates = [
        Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Edge/Application/msedge.exe',
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return shutil.which('msedge')


def launch_desktop(port: int | None = None, check_only: bool = False, no_window: bool = False) -> int:
    dist = ROOT / 'frontend' / 'dist' / 'index.html'
    if not dist.is_file():
        raise RuntimeError('未找到前端构建产物 frontend/dist，请先运行 setup.ps1 构建界面')
    chosen_port = pick_port(port or 8765)
    url = f'http://{HOST}:{chosen_port}'
    log_root = ROOT / 'storage' / 'runtime-logs'
    prune_old_logs(log_root, keep=10)
    logs = log_root / f'desktop-{uuid.uuid4().hex[:12]}'
    logs.mkdir(parents=True, exist_ok=True)

    origins = f'{url},http://localhost:{chosen_port}'
    env = dict(
        os.environ,
        PAPERMIND_SERVE_DIST='1',
        PAPERMIND_ORIGINS=origins,
        PYTHONUTF8='1',
    )

    with ExitStack() as stack:
        def start(label: str, args: list[str]):
            out = stack.enter_context((logs / f'{label}.out.txt').open('wb'))
            err = stack.enter_context((logs / f'{label}.err.txt').open('wb'))
            proc, job = start_owned(args, cwd=ROOT, env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
            stack.callback(stop_owned, proc, job)
            return proc

        server = start('api', [sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', HOST, '--port', str(chosen_port), '--no-access-log'])
        wait_for(lambda: http_ready(url + '/api/health'), server, 'API 服务')
        wait_for(lambda: http_ready(url + '/'), server, '桌面前端界面')

        worker_args = ['-c', WORKER_WITH_ENV] if (ROOT / '.env').is_file() else ['-m', 'backend.worker']
        worker = start('worker', [sys.executable, *worker_args])
        wait_for(lambda: b' ready' in (logs / 'worker.err.txt').read_bytes(), worker, '后台任务调度器')

        print(f'PaperMind Desktop Ready: {url}/', flush=True)
        if check_only:
            return 0

        app_proc = None
        if not no_window:
            version_tag = int(dist.stat().st_mtime)
            app_url = f'{url}/?v={version_tag}'
            edge = find_edge_binary()
            if edge:
                profile = ROOT / 'storage' / 'desktop-webview-profile'
                profile.mkdir(parents=True, exist_ok=True)
                app_proc = subprocess.Popen(
                    [
                        edge,
                        f'--app={app_url}',
                        f'--user-data-dir={profile}',
                        '--window-size=1440,920',
                        '--no-first-run',
                        '--no-default-browser-check',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                webbrowser.open(app_url)

        while True:
            if server.poll() is not None or worker.poll() is not None:
                raise RuntimeError(f'PaperMind 后台组件意外退出，请检查日志：{logs}')
            if app_proc is not None and app_proc.poll() is not None:
                # User closed the standalone PaperMind desktop window -> exit cleanly!
                return 0
            time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description='PaperMind Standalone Desktop Launcher')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--no-window', action='store_true')
    args = parser.parse_args()
    try:
        return launch_desktop(port=args.port, check_only=args.check_only, no_window=args.no_window)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f'PaperMind Desktop Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
