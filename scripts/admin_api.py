#!/usr/bin/env python3
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / 'scripts'
CONFIG_PATH = BASE_DIR / 'config' / 'strm-sync.yaml'
HTPASSWD_PATH = BASE_DIR / 'nginx' / 'conf.d' / '.htpasswd-xstrm-admin'
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


def update_basic_auth_password(new_password: str) -> tuple[bool, str]:
    new_password = (new_password or '').strip()
    if len(new_password) < 8:
        return False, '新密码至少 8 位'
    salt_proc = subprocess.run(['openssl', 'passwd', '-apr1', new_password], capture_output=True, text=True)
    if salt_proc.returncode != 0:
        return False, (salt_proc.stderr or salt_proc.stdout or '生成密码哈希失败').strip()
    HTPASSWD_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTPASSWD_PATH.write_text(f"admin:{salt_proc.stdout.strip()}\n", encoding='utf-8')
    HTPASSWD_PATH.chmod(0o600)
    reload_proc = subprocess.run(['docker', 'exec', 'xstrm-nginx', 'nginx', '-s', 'reload'], capture_output=True, text=True)
    if reload_proc.returncode != 0:
        return False, (reload_proc.stderr or reload_proc.stdout or 'nginx reload 失败').strip()
    return True, '管理密码已更新并生效'


def load_sync_config() -> dict:
    import yaml
    if not CONFIG_PATH.exists():
        return {}
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8')) or {}
    return data if isinstance(data, dict) else {}


def save_sync_config(data: dict):
    import yaml
    CONFIG_PATH.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')


def load_nginx_profile(profile_root: str | None = None) -> tuple[bool, dict | str]:
    target = profile_root or '/root/emby2Alist/nginx'
    code, out, err = run_cmd(['python3', str(SCRIPTS_DIR / 'load_nginx_profile.py'), '--root', target])
    if code != 0:
        return False, (err or out or '解析 nginx 配置失败').strip()
    try:
        return True, json.loads(out)
    except Exception:
        return False, '解析结果不是有效 JSON'


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
        if parsed.path == '/api/admin/xstrm/sources':
            cfg = load_sync_config()
            return self._json(200, {'ok': True, 'sources': cfg.get('sources', [])})
        if parsed.path == '/api/admin/xstrm/settings':
            cfg = load_sync_config()
            selected_mode = cfg.get('strm_mode', 'auto')
            ok, profile = load_nginx_profile(cfg.get('emby2alist', {}).get('profile_root'))
            resolved_mode = profile.get('preferredStrmMode', 'logical_path') if ok and selected_mode == 'auto' else selected_mode
            return self._json(200, {
                'ok': True,
                'settings': {
                    'strm_mode': selected_mode,
                    'resolved_strm_mode': resolved_mode,
                    'output_root': cfg.get('output_root', '/emby-strm'),
                    'profile_root': cfg.get('emby2alist', {}).get('profile_root', '/root/emby2Alist/nginx'),
                    'media_mount_path': cfg.get('emby2alist', {}).get('media_mount_path', []),
                },
                'profile': profile if ok else None,
                'profile_error': None if ok else profile,
            })
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

        if parsed.path == '/api/admin/xstrm/change-password':
            password = (data.get('password') or '').strip()
            confirm = (data.get('confirm') or '').strip()
            if not password:
                return self._json(400, {'ok': False, 'error': 'password required'})
            if password != confirm:
                return self._json(400, {'ok': False, 'error': '两次输入的密码不一致'})
            ok, message = update_basic_auth_password(password)
            return self._json(200 if ok else 500, {'ok': ok, 'message': message})

        if parsed.path == '/api/admin/xstrm/sources':
            new_sources = data.get('sources', [])
            cfg = load_sync_config()
            cfg['sources'] = new_sources
            save_sync_config(cfg)
            return self._json(200, {'ok': True, 'message': '同步源列表已更新', 'sources': new_sources})

        if parsed.path == '/api/admin/xstrm/settings':
            strm_mode = (data.get('strm_mode') or 'auto').strip()
            profile_root = (data.get('profile_root') or '/root/emby2Alist/nginx').strip()
            output_root = (data.get('output_root') or '/emby-strm').strip()
            if strm_mode not in ('auto', 'logical_path', 'local_path'):
                return self._json(400, {'ok': False, 'error': 'invalid strm_mode'})
            if not profile_root:
                return self._json(400, {'ok': False, 'error': 'profile_root required'})
            cfg = load_sync_config()
            cfg['strm_mode'] = strm_mode
            cfg['output_root'] = output_root or '/emby-strm'
            cfg.setdefault('emby2alist', {})['profile_root'] = profile_root
            ok, profile = load_nginx_profile(profile_root)
            if ok:
                cfg['emby2alist']['media_mount_path'] = profile.get('mediaMountPath', [])
                cfg['resolved_strm_mode'] = profile.get('preferredStrmMode', 'logical_path') if strm_mode == 'auto' else strm_mode
            save_sync_config(cfg)
            return self._json(200, {
                'ok': True,
                'message': '生成配置已更新',
                'settings': {
                    'strm_mode': cfg.get('strm_mode'),
                    'resolved_strm_mode': cfg.get('resolved_strm_mode'),
                    'output_root': cfg.get('output_root'),
                    'profile_root': cfg.get('emby2alist', {}).get('profile_root'),
                    'media_mount_path': cfg.get('emby2alist', {}).get('media_mount_path', []),
                },
                'profile': profile if ok else None,
                'profile_error': None if ok else profile,
            })

        return self._json(404, {'ok': False, 'error': 'not found'})


if __name__ == '__main__':
    print(f'xstrm admin api listening on http://{HOST}:{PORT}')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
