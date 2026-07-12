#!/usr/bin/env python3
import json
import subprocess
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest, error as urlerror
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / 'scripts'
WEB_DIR = BASE_DIR / 'web' / 'admin'
CONFIG_PATH = BASE_DIR / 'config' / 'strm-sync.yaml'
HTPASSWD_PATH = BASE_DIR / 'nginx' / 'conf.d' / '.htpasswd-xstrm-admin'
HOST = '127.0.0.1'
PORT = 18095

TASKS = {
    'scan': ['bash', str(SCRIPTS_DIR / 'task_incremental_refresh.sh')],
    'scan_full': ['bash', str(SCRIPTS_DIR / 'task_scan_incremental.sh')],
    'rebuild': ['bash', str(SCRIPTS_DIR / 'task_rebuild_all.sh')],
    'status': ['bash', str(SCRIPTS_DIR / 'task_status.sh')],
}


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def start_cmd(cmd: list[str]) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


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
    temporary = CONFIG_PATH.with_name(CONFIG_PATH.name + '.tmp')
    temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(CONFIG_PATH)


def derive_sources_preview(profile: dict, resolved_mode: str) -> tuple[list[dict], str | None]:
    payload = json.dumps({
        'emby2alist': {'media_mount_path': profile.get('mediaMountPath', [])},
        'strm_mode': resolved_mode,
        'resolved_strm_mode': resolved_mode,
        'sources': [],
    }, ensure_ascii=False)
    proc = subprocess.run([sys.executable, '-c', "import json, sys; from scripts.strm_x import ensure_integrated_config, build_example_target; cfg = ensure_integrated_config(json.loads(sys.stdin.read())); print(json.dumps({'sources': cfg.get('sources', []), 'expected_target_example': build_example_target(cfg)}, ensure_ascii=False))"], cwd=BASE_DIR, input=payload, capture_output=True, text=True)
    if proc.returncode != 0:
        return [], None
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return [], None
    return data.get('sources', []), data.get('expected_target_example')

def load_nginx_profile(profile_root: str | None = None) -> tuple[bool, dict | str]:
    target = profile_root or '/opt/xstrm-suite/nginx'
    code, out, err = run_cmd(['python3', str(SCRIPTS_DIR / 'load_nginx_profile.py'), '--root', target])
    if code != 0:
        return False, (err or out or '解析 nginx 配置失败').strip()
    try:
        return True, json.loads(out)
    except Exception:
        return False, '解析结果不是有效 JSON'


def alist_list_dir(path: str) -> tuple[bool, dict | str]:
    cfg = load_sync_config()
    alist = cfg.get('alist', {}) or {}
    base_url = (alist.get('base_url') or '').rstrip('/')
    token = (alist.get('token') or '').strip()
    if not base_url:
        return False, 'alist.base_url 未配置'
    if not token:
        return False, 'alist.token 未配置'
    target_path = (path or '/').strip() or '/'
    if not target_path.startswith('/'):
        target_path = '/' + target_path
    req = urlrequest.Request(base_url + '/api/fs/list', method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', token)
    body = json.dumps({
        'path': target_path,
        'password': '',
        'page': 1,
        'per_page': 0,
        'refresh': False,
    }, ensure_ascii=False).encode('utf-8')
    try:
        with urlrequest.urlopen(req, data=body, timeout=30) as resp:
            raw = resp.read().decode('utf-8', 'ignore')
    except urlerror.HTTPError as e:
        raw = e.read().decode('utf-8', 'ignore') if e.fp else ''
        return False, f'AList API HTTP {e.code}: {raw[:200]}'
    except Exception as e:
        return False, f'AList API 请求失败: {e}'
    try:
        data = json.loads(raw)
    except Exception:
        return False, f'AList API 返回非 JSON: {raw[:200]}'
    if data.get('code') != 200:
        return False, data.get('message') or data.get('msg') or 'AList API 错误'
    content = ((data.get('data') or {}).get('content') or [])
    items = []
    for item in content:
        name = item.get('name') or ''
        if not name:
            continue
        child = f"{target_path.rstrip('/')}/{name}" if target_path != '/' else f'/{name}'
        is_dir = bool(item.get('is_dir')) or int(item.get('type') or 0) == 1
        items.append({
            'name': name,
            'path': child,
            'is_dir': is_dir,
            'size': item.get('size'),
            'modified': item.get('modified') or item.get('updated_at') or item.get('updated'),
        })
    # 先按修改日期降序（新→旧），再按类型稳定排序（目录在前）
    items.sort(key=lambda x: x.get('modified') or '', reverse=True)
    items.sort(key=lambda x: not x['is_dir'])
    return True, {'path': target_path, 'items': items}


class Handler(BaseHTTPRequestHandler):
    server_version = 'xstrm-admin-api/0.1'

    def _send_bytes(self, code: int, body: bytes, content_type: str, write_body: bool = True):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _json(self, code: int, data: dict, write_body: bool = True):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self._send_bytes(code, body, 'application/json; charset=utf-8', write_body=write_body)

    def _html(self, code: int, html: str, write_body: bool = True):
        body = html.encode('utf-8')
        self._send_bytes(code, body, 'text/html; charset=utf-8', write_body=write_body)

    def log_message(self, fmt, *args):
        return

    def _handle_get(self, write_body: bool = True):
        parsed = urlparse(self.path)
        if parsed.path in ('/admin/xstrm', '/admin/xstrm/'):
            index = WEB_DIR / 'index.html'
            if not index.exists():
                return self._html(404, 'xstrm admin index.html not found', write_body=write_body)
            return self._html(200, index.read_text(encoding='utf-8'), write_body=write_body)
        if parsed.path == '/admin/xstrm/index.html':
            index = WEB_DIR / 'index.html'
            if not index.exists():
                return self._html(404, 'xstrm admin index.html not found', write_body=write_body)
            return self._html(200, index.read_text(encoding='utf-8'), write_body=write_body)
        if parsed.path == '/api/admin/xstrm/status':
            code, out, err = run_cmd(TASKS['status'])
            if code == 0:
                try:
                    payload = json.loads(out)
                except Exception:
                    payload = {'raw': out}
                return self._json(200, {'ok': True, 'status': payload}, write_body=write_body)
            return self._json(500, {'ok': False, 'error': err or out}, write_body=write_body)
        if parsed.path == '/api/admin/xstrm/incremental/status':
            code, out, err = run_cmd([
                sys.executable,
                str(SCRIPTS_DIR / 'incremental_strm_refresh.py'),
                '--config', str(CONFIG_PATH),
                'status',
            ])
            if code == 0:
                return self._json(200, {'ok': True, 'incremental': json.loads(out)}, write_body=write_body)
            return self._json(500, {'ok': False, 'error': err or out}, write_body=write_body)
        if parsed.path == '/api/admin/xstrm/logs/latest':
            status_file = BASE_DIR / 'data' / 'tasks' / 'status.json'
            if not status_file.exists():
                return self._json(200, {'ok': True, 'log_file': None, 'content': ''}, write_body=write_body)
            status = json.loads(status_file.read_text(encoding='utf-8'))
            log_file = status.get('log_file')
            content = ''
            if log_file and Path(log_file).exists():
                content = Path(log_file).read_text(encoding='utf-8', errors='ignore')[-12000:]
            return self._json(200, {'ok': True, 'log_file': log_file, 'content': content}, write_body=write_body)
        if parsed.path == '/api/admin/xstrm/strm-health':
            code, out, err = run_cmd([sys.executable, str(SCRIPTS_DIR / 'strm_health_check.py')])
            if code == 0:
                return self._json(200, {'ok': True, 'report': json.loads(out)}, write_body=write_body)
            return self._json(500, {'ok': False, 'error': err or out or 'strm health check failed'}, write_body=write_body)
        if parsed.path == '/api/admin/xstrm/sources':
            cfg = load_sync_config()
            return self._json(200, {'ok': True, 'sources': cfg.get('sources', [])}, write_body=write_body)
        if parsed.path == '/api/admin/xstrm/alist/list':
            query = parse_qs(parsed.query)
            path = (query.get('path') or ['/'])[0]
            ok, payload = alist_list_dir(path)
            if ok:
                return self._json(200, {'ok': True, **payload}, write_body=write_body)
            return self._json(500, {'ok': False, 'error': payload, 'path': path}, write_body=write_body)
        if parsed.path == '/api/admin/xstrm/settings':
            cfg = load_sync_config()
            selected_mode = cfg.get('strm_mode', 'auto')
            ok, profile = load_nginx_profile(cfg.get('emby2alist', {}).get('profile_root'))
            resolved_mode = profile.get('preferredStrmMode', 'logical_path') if ok and selected_mode == 'auto' else selected_mode
            derived_sources, expected_example = derive_sources_preview(profile if ok else {}, resolved_mode)
            return self._json(200, {
                'ok': True,
                'settings': {
                    'strm_mode': selected_mode,
                    'resolved_strm_mode': resolved_mode,
                    'output_root': cfg.get('output_root', '/emby-strm'),
                    'profile_root': cfg.get('emby2alist', {}).get('profile_root', '/opt/xstrm-suite/nginx'),
                    'media_mount_path': cfg.get('emby2alist', {}).get('media_mount_path', []),
                    'derived_sources': derived_sources,
                    'expected_target_example': expected_example,
                },
                'profile': profile if ok else None,
                'profile_error': None if ok else profile,
            }, write_body=write_body)
        return self._json(404, {'ok': False, 'error': 'not found'}, write_body=write_body)

    def do_GET(self):
        return self._handle_get(write_body=True)

    def do_HEAD(self):
        return self._handle_get(write_body=False)

    def _handle_post(self):
        parsed = urlparse(self.path)
        if self.headers.get('X-XSTRM-Requested-With') != 'xstrm-admin':
            return self._json(403, {'ok': False, 'error': 'missing request verification header'})
        length = int(self.headers.get('Content-Length', '0'))
        if length > 1024 * 1024:
            return self._json(413, {'ok': False, 'error': 'request body too large'})
        raw = self.rfile.read(length).decode('utf-8') if length else ''
        data = {}
        if raw:
            try:
                data = json.loads(raw)
            except Exception:
                data = {k: v[0] for k, v in parse_qs(raw).items()}

        if parsed.path == '/api/admin/xstrm/scan':
            pid = start_cmd(TASKS['scan'])
            return self._json(202, {'ok': True, 'pid': pid, 'message': '增量刷新任务已提交'})

        if parsed.path == '/api/admin/xstrm/scan-full':
            pid = start_cmd(TASKS['scan_full'])
            return self._json(202, {'ok': True, 'pid': pid, 'message': '完整校验任务已提交'})

        if parsed.path == '/api/admin/xstrm/rebuild':
            pid = start_cmd(TASKS['rebuild'])
            return self._json(202, {'ok': True, 'pid': pid, 'message': '全量重建任务已提交'})

        if parsed.path == '/api/admin/xstrm/scan-path':
            target = (data.get('path') or '').strip()
            if not target:
                return self._json(400, {'ok': False, 'error': 'path required'})
            pid = start_cmd(['bash', str(SCRIPTS_DIR / 'task_incremental_refresh.sh'), target])
            return self._json(202, {'ok': True, 'pid': pid, 'path': target, 'message': '指定目录已加入递归刷新队列'})

        if parsed.path in ('/api/admin/xstrm/ignore', '/api/admin/xstrm/unignore'):
            target = (data.get('path') or '').strip()
            if not target:
                return self._json(400, {'ok': False, 'error': 'path required'})
            command = 'ignore-path' if parsed.path.endswith('/ignore') else 'unignore-path'
            cmd = [sys.executable, str(SCRIPTS_DIR / 'incremental_strm_refresh.py'), '--config', str(CONFIG_PATH), command, target]
            if command == 'ignore-path':
                cmd.extend(['--reason', 'web_manual'])
            code, out, err = run_cmd(cmd)
            return self._json(200 if code == 0 else 500, {'ok': code == 0, 'message': out.strip(), 'error': err.strip()})

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
            profile_root = (data.get('profile_root') or '/opt/xstrm-suite/nginx').strip()
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
            derived_sources, expected_example = derive_sources_preview(profile if ok else {}, cfg.get('resolved_strm_mode', strm_mode))
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
                    'derived_sources': derived_sources,
                    'expected_target_example': expected_example,
                },
                'profile': profile if ok else None,
                'profile_error': None if ok else profile,
            })

        return self._json(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        try:
            return self._handle_post()
        except PermissionError:
            traceback.print_exc()
            return self._json(500, {
                'ok': False,
                'error': '保存配置失败：服务账户没有配置目录写权限，请重新运行安装或升级脚本修复权限',
            })
        except Exception:
            traceback.print_exc()
            return self._json(500, {'ok': False, 'error': '服务器处理请求失败，请检查 xstrm-admin-api 日志'})


if __name__ == '__main__':
    print(f'xstrm admin api listening on http://{HOST}:{PORT}')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
