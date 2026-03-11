#!/usr/bin/env python3
import json
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_PATH = BASE_DIR / 'config' / 'runtime.yaml'
TEMPLATE_DIR = BASE_DIR / 'config' / 'templates'
OUT_NGINX_DIR = BASE_DIR / 'nginx'
OUT_STRM_SYNC = BASE_DIR / 'config' / 'strm-sync.yaml'
OUT_SITES_DIR = OUT_NGINX_DIR / 'sites-enabled'
OUT_COMPOSE = BASE_DIR / 'docker-compose.yml'


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def quoted_list(values):
    return ', '.join(json.dumps(v, ensure_ascii=False) for v in values)


def yaml_list(values, indent=4):
    pad = ' ' * indent
    return '\n'.join(f'{pad}- {v}' for v in values)


def render_template(path: Path, mapping: dict):
    text = path.read_text(encoding='utf-8')
    for key, value in mapping.items():
        text = text.replace('{{ ' + key + ' }}', str(value))
    return text


def build_mapping(cfg: dict):
    mount_paths = cfg.get('mount', {}).get('media_mount_path', [])
    sources = cfg.get('xstrm', {}).get('sources', [])
    source_lines = []
    for src in sources:
        source_lines.append(f"- path: {src}")
        source_lines.append('  library_type: movie' if src.endswith('/电影') else '  library_type: series')
        source_lines.append('  watch_depth: 1')
        source_lines.append(f'  output_prefix: {src}')
        scan_path = f"{mount_paths[0]}{src}" if mount_paths else src
        source_lines.append(f'  scan_path: {scan_path}')
    alist_addr = f"{cfg['alist'].get('scheme', 'http')}://{cfg['alist']['host']}:{cfg['alist']['port']}"
    cert_mount_block = ''
    if cfg['nginx'].get('https_enabled') and cfg['nginx'].get('ssl_cert'):
        cert_dir = str(Path(cfg['nginx']['ssl_cert']).resolve().parent)
        cert_mount_block = f'      - {cert_dir}:/etc/nginx/conf.d/cert:ro'
    return {
        'emby.host': cfg['emby']['host'],
        'emby.api_key': cfg['emby']['api_key'],
        'mount.media_mount_path_quoted': quoted_list(mount_paths),
        'alist.addr': alist_addr,
        'alist.token': cfg['alist']['token'],
        'alist.public_addr': cfg['alist']['public_addr'],
        'alist.sign_enable_js': 'true' if cfg['alist'].get('sign_enable') else 'false',
        'alist.sign_expire_time': cfg['alist'].get('sign_expire_time', 12),
        'project.install_root': cfg['project']['install_root'],
        'xstrm.output_root': cfg['xstrm']['output_root'],
        'xstrm.mode': cfg['xstrm'].get('mode', 'mirror'),
        'xstrm.incremental_only_yaml': 'true' if cfg['xstrm'].get('incremental_only', True) else 'false',
        'xstrm.sources_yaml': '\n'.join(source_lines),
        'mount.media_mount_path_yaml': yaml_list(mount_paths),
        'nginx.http_port': cfg['nginx']['http_port'],
        'nginx.https_enabled': str(cfg['nginx']['https_enabled']).lower(),
        'nginx.https_port': cfg['nginx']['https_port'],
        'nginx.server_name': cfg['nginx']['server_name'],
        'nginx.ssl_cert': cfg['nginx'].get('ssl_cert', ''),
        'nginx.ssl_key': cfg['nginx'].get('ssl_key', ''),
        'nginx.backend_scheme': cfg['nginx'].get('backend_scheme', 'http'),
        'nginx.backend_port': cfg['nginx'].get('backend_port', 8095),
        'docker.cert_mount_block': cert_mount_block,
    }


def main():
    cfg = load_yaml(RUNTIME_PATH)
    mapping = build_mapping(cfg)

    (OUT_NGINX_DIR / 'conf.d').mkdir(parents=True, exist_ok=True)
    (OUT_NGINX_DIR / 'conf.d' / 'config').mkdir(parents=True, exist_ok=True)

    constant_js = render_template(TEMPLATE_DIR / 'constant.js.template', mapping)
    constant_mount = render_template(TEMPLATE_DIR / 'constant-mount.js.template', mapping)
    strm_sync = render_template(TEMPLATE_DIR / 'strm-sync.yaml.template', mapping)
    nginx_patch = render_template(TEMPLATE_DIR / 'nginx.conf.patch.template', mapping)
    site_http = render_template(TEMPLATE_DIR / 'site-http.conf.template', mapping)
    site_https = render_template(TEMPLATE_DIR / 'site-https.conf.template', mapping)
    docker_compose = render_template(TEMPLATE_DIR / 'docker-compose.yml.template', mapping)

    (OUT_NGINX_DIR / 'conf.d' / 'constant.js.runtime').write_text(constant_js, encoding='utf-8')
    (OUT_NGINX_DIR / 'conf.d' / 'config' / 'constant-mount.runtime.js').write_text(constant_mount, encoding='utf-8')
    OUT_STRM_SYNC.write_text(strm_sync, encoding='utf-8')
    (OUT_NGINX_DIR / 'nginx.runtime.conf').write_text(nginx_patch, encoding='utf-8')
    OUT_SITES_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_SITES_DIR / 'xstrm-http.conf').write_text(site_http, encoding='utf-8')
    if cfg['nginx'].get('https_enabled'):
        (OUT_SITES_DIR / 'xstrm-https.conf').write_text(site_https, encoding='utf-8')
    elif (OUT_SITES_DIR / 'xstrm-https.conf').exists():
        (OUT_SITES_DIR / 'xstrm-https.conf').unlink()
    OUT_COMPOSE.write_text(docker_compose, encoding='utf-8')

    print('render complete:')
    print(f'- {OUT_NGINX_DIR / "conf.d" / "constant.js.runtime"}')
    print(f'- {OUT_NGINX_DIR / "conf.d" / "config" / "constant-mount.runtime.js"}')
    print(f'- {OUT_STRM_SYNC}')
    print(f'- {OUT_NGINX_DIR / "nginx.runtime.conf"}')
    print(f'- {OUT_SITES_DIR / "xstrm-http.conf"}')
    if cfg['nginx'].get('https_enabled'):
        print(f'- {OUT_SITES_DIR / "xstrm-https.conf"}')
    print(f'- {OUT_COMPOSE}')


if __name__ == '__main__':
    main()
