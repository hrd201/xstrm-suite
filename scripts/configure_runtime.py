#!/usr/bin/env python3
from pathlib import Path
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_PATH = BASE_DIR / 'config' / 'runtime.yaml'


def ask(prompt: str, default: str = '') -> str:
    suffix = f' [{default}]' if default else ''
    value = input(f'{prompt}{suffix}: ').strip()
    return value or default


def ask_bool(prompt: str, default: bool = False) -> bool:
    default_str = 'y' if default else 'n'
    value = input(f'{prompt} [y/n, default {default_str}]: ').strip().lower()
    if not value:
        return default
    return value in ('y', 'yes', '1', 'true')


def ask_choice(prompt: str, choices: dict, default_key: str) -> str:
    print(prompt)
    for k, v in choices.items():
        print(f'  {k}. {v}')
    value = input(f'请选择 [默认 {default_key}]: ').strip()
    return value or default_key


def load_runtime() -> dict:
    if not RUNTIME_PATH.exists():
        return {}
    return yaml.safe_load(RUNTIME_PATH.read_text(encoding='utf-8')) or {}


def save_runtime(data: dict):
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_PATH.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')


def main():
    cfg = load_runtime()
    cfg.setdefault('project', {})
    cfg.setdefault('emby', {})
    cfg.setdefault('alist', {})
    cfg.setdefault('nginx', {})
    cfg.setdefault('mount', {})
    cfg.setdefault('xstrm', {})

    print('\n=== 配置 xstrm-suite runtime ===')
    cfg['project']['install_root'] = ask('安装目录', cfg['project'].get('install_root', '/opt/xstrm-suite'))

    cfg['emby']['host'] = ask('Emby 地址', cfg['emby'].get('host', 'http://127.0.0.1:8096'))
    cfg['emby']['api_key'] = ask('Emby API Key', cfg['emby'].get('api_key', ''))

    alist_mode = ask_choice('请选择 AList 安装方式', {
        '1': 'Docker 安装（默认地址建议 http://YOUR_ALIST_HOST:5388）',
        '2': '本机直接安装（默认地址建议 http://127.0.0.1:5388）',
        '3': '自定义地址',
    }, '1')
    if alist_mode == '1':
        default_alist_host = '172.17.0.1'
    elif alist_mode == '2':
        default_alist_host = '127.0.0.1'
    else:
        default_alist_host = cfg['alist'].get('host', '')
    cfg['alist']['scheme'] = ask('AList 协议（http/https）', cfg['alist'].get('scheme', 'http'))
    cfg['alist']['host'] = ask('AList 主机/IP', cfg['alist'].get('host', default_alist_host) or default_alist_host)
    cfg['alist']['port'] = int(ask('AList 端口', str(cfg['alist'].get('port', 5244))))
    cfg['alist']['token'] = ask('AList Token', cfg['alist'].get('token', ''))
    default_public = cfg['alist'].get('public_addr', f"{cfg['alist']['scheme']}://{cfg['alist']['host']}:{cfg['alist']['port']}")
    cfg['alist']['public_addr'] = ask('AList 公网地址', default_public)
    cfg['alist']['sign_enable'] = ask_bool('是否启用 AList sign', cfg['alist'].get('sign_enable', False))
    cfg['alist']['sign_expire_time'] = int(ask('AList 直链有效期（小时）', str(cfg['alist'].get('sign_expire_time', 12))))

    cfg['nginx']['server_name'] = ask('nginx server_name', cfg['nginx'].get('server_name', '_'))
    cfg['nginx']['http_port'] = int(ask('nginx HTTP 对外端口', str(cfg['nginx'].get('http_port', 8095))))
    cfg['nginx']['backend_scheme'] = ask('nginx 后端协议（http/https）', cfg['nginx'].get('backend_scheme', 'http'))
    cfg['nginx']['backend_port'] = int(ask('nginx 后端代理端口', str(cfg['nginx'].get('backend_port', 18095))))
    https_enabled = ask_bool('是否启用 HTTPS', cfg['nginx'].get('https_enabled', False))
    cfg['nginx']['https_enabled'] = https_enabled
    cfg['nginx']['https_port'] = int(ask('nginx HTTPS 对外端口', str(cfg['nginx'].get('https_port', 8443))))
    if https_enabled:
        cfg['nginx']['ssl_cert'] = ask('SSL 证书路径', cfg['nginx'].get('ssl_cert', ''))
        cfg['nginx']['ssl_key'] = ask('SSL 私钥路径', cfg['nginx'].get('ssl_key', ''))
    else:
        cfg['nginx']['ssl_cert'] = ''
        cfg['nginx']['ssl_key'] = ''

    mount_path = ask('媒体挂载根路径（逗号分隔）', ','.join(cfg.get('mount', {}).get('media_mount_path', ['/mnt'])))
    cfg['mount']['media_mount_path'] = [x.strip() for x in mount_path.split(',') if x.strip()]

    cfg['xstrm']['output_root'] = ask('STRM 输出目录', cfg.get('xstrm', {}).get('output_root', '/emby-strm'))
    cfg['xstrm']['mode'] = ask('STRM 模式', cfg.get('xstrm', {}).get('mode', 'mirror'))
    cfg['xstrm']['incremental_only'] = ask_bool('是否仅增量生成', cfg.get('xstrm', {}).get('incremental_only', True))

    sources_default = cfg.get('xstrm', {}).get('sources', ['/115/电影', '/115/剧集', '/115/动画'])
    sources = ask('扫描源列表（逗号分隔）', ','.join(sources_default))
    cfg['xstrm']['sources'] = [x.strip() for x in sources.split(',') if x.strip()]

    save_runtime(cfg)
    print(f'\n[done] runtime config saved to: {RUNTIME_PATH}')


if __name__ == '__main__':
    main()
