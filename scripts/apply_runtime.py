#!/usr/bin/env python3
from pathlib import Path
import shutil
import re
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_PATH = BASE_DIR / 'config' / 'runtime.yaml'
NGINX_DIR = BASE_DIR / 'nginx'


def backup(path: Path):
    if path.exists():
        bak = path.with_suffix(path.suffix + '.bak') if path.suffix else Path(str(path) + '.bak')
        shutil.copy2(path, bak)


def load_runtime():
    return yaml.safe_load(RUNTIME_PATH.read_text(encoding='utf-8')) or {}


def apply_runtime_files():
    runtime_constant = NGINX_DIR / 'conf.d' / 'constant.js.runtime'
    live_constant = NGINX_DIR / 'conf.d' / 'constant.js'
    runtime_mount = NGINX_DIR / 'conf.d' / 'config' / 'constant-mount.runtime.js'
    live_mount = NGINX_DIR / 'conf.d' / 'config' / 'constant-mount.js'

    if runtime_constant.exists():
        backup(live_constant)
        shutil.copy2(runtime_constant, live_constant)
    if runtime_mount.exists():
        backup(live_mount)
        shutil.copy2(runtime_mount, live_mount)


def patch_nginx_conf(cfg: dict):
    nginx_conf = NGINX_DIR / 'nginx.conf'
    if not nginx_conf.exists():
        return
    backup(nginx_conf)
    text = nginx_conf.read_text(encoding='utf-8')
    header = (
        f'# xstrm runtime\n'
        f'# http_port={cfg["nginx"]["http_port"]}\n'
        f'# https_enabled={str(cfg["nginx"]["https_enabled"]).lower()}\n'
        f'# https_port={cfg["nginx"]["https_port"]}\n'
        f'# backend_scheme={cfg["nginx"].get("backend_scheme", "http")}\n'
        f'# backend_port={cfg["nginx"].get("backend_port", 8095)}\n'
        f'# server_name={cfg["nginx"]["server_name"]}\n'
        f'# ssl_cert={cfg["nginx"].get("ssl_cert", "")}\n'
        f'# ssl_key={cfg["nginx"].get("ssl_key", "")}\n'
    )
    text = re.sub(r'^(# xstrm runtime\n(?:# .*\n){0,8})', '', text, flags=re.M)
    if 'include sites-enabled/*.conf;' not in text:
        marker = '    include /etc/nginx/conf.d/*.conf;\n'
        if marker in text:
            text = text.replace(marker, marker + '    include sites-enabled/*.conf;\n')
    nginx_conf.write_text(header + text, encoding='utf-8')


def main():
    cfg = load_runtime()
    apply_runtime_files()
    patch_nginx_conf(cfg)
    print('apply complete: runtime config copied into live nginx/emby2alist files')


if __name__ == '__main__':
    main()
