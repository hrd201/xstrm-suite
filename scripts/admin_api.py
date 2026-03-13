#!/usr/bin/env python3
import json
import shlex
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / 'scripts'
HOST = '127.0.0.1'
PORT = 18095

TASKS = {
    'scan': ['bash', str(SCRIPTS_DIR / 'task_scan_incremental.sh')],
    'rebuild': ['bash', str(SCRIPTS_DIR / 'task_rebuild_all.sh')],
    'status': ['bash', str(SCRIPTS_DIR / 'task_status.sh')],
}


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class Handler(BaseHTTPRequestHandler):
    server_version = 'xstrm-admin-api/0.1'

    def _json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/admin/xstrm/status':
            code, out, err = run_cmd(TASKS['status'])
            if code == 0:
                try:
                    payload = json.loads(out)
                except Exception:
                    payload = {'raw': out}
                return self._json(200, {'ok': True, 'status': payload})
            return self._json(500, {'ok': False, 'error': err or out})
        if parsed.path == '/api/admin/xstrm/logs/latest':
            status_file = BASE_DIR / 'data' / 'tasks' / 'status.json'
            if not status_file.exists():
                return self._json(200, {'ok': True, 'log_file': None, 'content': ''})
            status = json.loads(status_file.read_text(encoding='utf-8'))
            log_file = status.get('log_file')
            content = ''
            if log_file and Path(log_file).exists():
                content = Path(log_file).read_text(encoding='utf-8', errors='ignore')[-12000:]
            return self._json(200, {'ok': True, 'log_file': log_file, 'content': content})
        return self._json(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length).decode('utf-8') if length else ''
        data = {}
        if raw:
            try:
                data = json.loads(raw)
            except Exception:
                data = {k: v[0] for k, v in parse_qs(raw).items()}

        if parsed.path == '/api/admin/xstrm/scan':
            code, out, err = run_cmd(TASKS['scan'])
            return self._json(200 if code in (0, 2) else 500, {
                'ok': code in (0, 2),
                'exit_code': code,
                'stdout': out,
                'stderr': err,
            })

        if parsed.path == '/api/admin/xstrm/rebuild':
            code, out, err = run_cmd(TASKS['rebuild'])
            return self._json(200 if code in (0, 2) else 500, {
                'ok': code in (0, 2),
                'exit_code': code,
                'stdout': out,
                'stderr': err,
            })

        if parsed.path == '/api/admin/xstrm/scan-path':
            target = (data.get('path') or '').strip()
            if not target:
                return self._json(400, {'ok': False, 'error': 'path required'})
            code, out, err = run_cmd(['bash', str(SCRIPTS_DIR / 'task_scan_path.sh'), target])
            return self._json(200 if code in (0, 2) else 500, {
                'ok': code in (0, 2),
                'exit_code': code,
                'path': target,
                'stdout': out,
                'stderr': err,
            })

        return self._json(404, {'ok': False, 'error': 'not found'})


if __name__ == '__main__':
    print(f'xstrm admin api listening on http://{HOST}:{PORT}')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
