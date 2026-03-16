#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from urllib import request, error

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'strm-sync.yaml'
STATE_PATH = BASE_DIR / 'data' / 'strm-sync-state.json'
EMBY2ALIST_CONSTANT = BASE_DIR / 'emby2alist' / 'conf.d' / 'constant.js'
EMBY2ALIST_MOUNT_CONFIG = BASE_DIR / 'emby2alist' / 'conf.d' / 'config' / 'constant-mount.js'
DEFAULT_NGINX_PROFILE_ROOT = BASE_DIR / 'emby2alist'
MEDIA_EXTS = {'.mp4', '.mkv', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.flv'}


def load_simple_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    import yaml  # type: ignore
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict):
    import yaml  # type: ignore
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {'version': 1, 'sources': {}}
    return json.loads(STATE_PATH.read_text(encoding='utf-8'))


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def parse_js_string(text: str, name: str):
    m = re.search(rf'const\s+{re.escape(name)}\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else None


def parse_js_string_array(text: str, name: str):
    m = re.search(rf'const\s+{re.escape(name)}\s*=\s*\[([^\]]*)\]', text, re.S)
    if not m:
        return []
    return re.findall(r'"([^"]*)"', m.group(1))


def infer_emby2alist_settings() -> dict:
    result = {
        'mediaMountPath': [],
        'alistAddr': None,
        'alistToken': None,
        'alistPublicAddr': None,
        'preferredStrmMode': 'logical_path',
        'profileRoot': str(DEFAULT_NGINX_PROFILE_ROOT),
        'defaultSources': [],
    }
    if EMBY2ALIST_CONSTANT.exists():
        text = EMBY2ALIST_CONSTANT.read_text(encoding='utf-8')
        result['mediaMountPath'] = parse_js_string_array(text, 'mediaMountPath')
    if EMBY2ALIST_MOUNT_CONFIG.exists():
        text = EMBY2ALIST_MOUNT_CONFIG.read_text(encoding='utf-8')
        result['alistAddr'] = parse_js_string(text, 'alistAddr')
        result['alistToken'] = parse_js_string(text, 'alistToken')
        result['alistPublicAddr'] = parse_js_string(text, 'alistPublicAddr')
    pro_path = DEFAULT_NGINX_PROFILE_ROOT / 'conf.d' / 'config' / 'constant-pro.js'
    if pro_path.exists():
        pro_text = pro_path.read_text(encoding='utf-8')
        if '"/115/"' in pro_text and '/emby-strm/115/' in pro_text:
            result['preferredStrmMode'] = 'logical_path'
    return result


def infer_library_type(output_prefix: str) -> str:
    normalized = output_prefix.lower()
    if any(token in normalized for token in ('电影', 'movie', 'movies', 'film', 'films')):
        return 'movie'
    return 'series'


def build_example_target(config: dict) -> str:
    return '/115/示例/样片.mkv'


def ensure_integrated_config(config: dict) -> dict:
    config.setdefault('output_root', '/emby-strm')
    config.setdefault('state_file', str(STATE_PATH))
    config.setdefault('mode', 'mirror')
    config.setdefault('strm_mode', 'auto')
    config.setdefault('scan', {})
    config['scan'].setdefault('incremental_only', True)
    config['scan'].setdefault('include_ext', sorted(MEDIA_EXTS))
    config.setdefault('emby2alist', {})
    config.setdefault('alist', {})

    inferred = infer_emby2alist_settings()
    emby2alist = config['emby2alist']
    if not emby2alist.get('media_mount_path'):
        emby2alist['media_mount_path'] = inferred.get('mediaMountPath', [])
    if not emby2alist.get('profile_root'):
        emby2alist['profile_root'] = inferred.get('profileRoot')
    if config.get('strm_mode') == 'auto':
        config['resolved_strm_mode'] = inferred.get('preferredStrmMode', 'logical_path')
    else:
        config['resolved_strm_mode'] = config.get('strm_mode', 'logical_path')

    if not config['alist'].get('base_url') and inferred.get('alistAddr'):
        config['alist']['base_url'] = inferred['alistAddr']
    if not config['alist'].get('token') and inferred.get('alistToken'):
        config['alist']['token'] = inferred['alistToken']
    if not config['alist'].get('public_url') and inferred.get('alistPublicAddr'):
        config['alist']['public_url'] = inferred['alistPublicAddr']

    sources = config.setdefault('sources', [])
    for src in sources:
        if not src.get('library_type'):
            src['library_type'] = infer_library_type(src.get('output_prefix', src.get('scan_path', '')))
        src.setdefault('watch_depth', 1)
        normalize_source(src)
    return config


def normalize_source(src: dict):
    scan_mode = (src.get('scan_mode') or 'alist').strip().lower()
    if scan_mode != 'alist':
        scan_mode = 'alist'
    src['scan_mode'] = scan_mode
    if src.get('path') and not src.get('output_prefix'):
        src['output_prefix'] = src['path']
    if src.get('output_prefix') and not src.get('scan_path'):
        src['scan_path'] = src['output_prefix']
    if src.get('scan_path') and not src.get('output_prefix'):
        src['output_prefix'] = src['scan_path']
    output_prefix = (src.get('output_prefix') or '').rstrip('/')
    scan_path = (src.get('scan_path') or '').rstrip('/')
    if scan_mode == 'alist' and output_prefix and scan_path.startswith('/mnt/'):
        src['scan_path'] = output_prefix


def show_config(config: dict):
    print(f'配置文件: {CONFIG_PATH}')
    print(json.dumps(config, ensure_ascii=False, indent=2))


def show_state():
    print(f'状态文件: {STATE_PATH}')
    print(json.dumps(load_state(), ensure_ascii=False, indent=2))


def show_integration(config: dict):
    print('xstrm / emby2alist 集成配置：')
    print(json.dumps({
        'profile_root': config.get('emby2alist', {}).get('profile_root'),
        'media_mount_path': config.get('emby2alist', {}).get('media_mount_path', []),
        'alist': config.get('alist', {}),
        'strm_mode': config.get('strm_mode'),
        'resolved_strm_mode': config.get('resolved_strm_mode'),
        'sources': config.get('sources', []),
        'expected_target_example': build_example_target(config),
    }, ensure_ascii=False, indent=2))


def print_main_menu():
    print('\nXSTRM 菜单')
    print('1. 从已配置 AList 目录中选择扫描')
    print('2. 扫描指定 AList 目录')
    print('3. 查看同源配置')
    print('4. 定时扫描设定')
    print('5. 查看当前配置')
    print('6. 查看状态文件')
    print('0. 退出')


def normalize_output_path(output_root: str, media_path: str) -> Path:
    relative = media_path.lstrip('/')
    return Path(output_root) / Path(relative).with_suffix('.strm')


def resolve_strm_target(config: dict, media_path: str, full_path: str) -> str:
    # AList 目录扫描模式下，strm 内容就是逻辑路径本身。
    return media_path


def generate_one(output_root: str, media_path: str, target_path: str) -> Path:
    out = normalize_output_path(output_root, media_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(target_path, encoding='utf-8')
    print(f'已生成: {out}')
    return out


def record_generated(state: dict, source_key: str, media_paths: list):
    bucket = state['sources'].setdefault(source_key, {'generated': []})
    existing = set(bucket.get('generated', []))
    for media in media_paths:
        if media not in existing:
            bucket['generated'].append(media)


def prune_missing_state_entries(state: dict, source_key: str, output_root: str) -> int:
    bucket = state['sources'].setdefault(source_key, {'generated': []})
    generated = bucket.get('generated', []) or []
    kept = []
    removed = 0
    for media_path in generated:
        if normalize_output_path(output_root, media_path).exists():
            kept.append(media_path)
        else:
            removed += 1
    bucket['generated'] = kept
    return removed


def find_matching_source(config: dict, source_input: str):
    normalized = source_input.rstrip('/')
    for src in config.get('sources', []):
        if src.get('scan_path', '').rstrip('/') == normalized or src.get('output_prefix', '').rstrip('/') == normalized:
            return src
    return None


def alist_request(config: dict, api_path: str, payload: dict) -> dict:
    base_url = (config.get('alist', {}) or {}).get('base_url', '').rstrip('/')
    token = (config.get('alist', {}) or {}).get('token', '')
    if not base_url:
        raise RuntimeError('alist.base_url 未配置')
    if not token:
        raise RuntimeError('alist.token 未配置')
    url = f'{base_url}{api_path}'
    req = request.Request(url, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', token)
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    try:
        with request.urlopen(req, data=body, timeout=60) as resp:
            raw = resp.read().decode('utf-8', 'ignore')
    except error.HTTPError as e:
        raw = e.read().decode('utf-8', 'ignore') if e.fp else ''
        raise RuntimeError(f'AList API HTTP {e.code}: {raw[:200]}')
    except Exception as e:
        raise RuntimeError(f'AList API 请求失败: {e}')
    try:
        data = json.loads(raw)
    except Exception:
        raise RuntimeError(f'AList API 返回非 JSON: {raw[:200]}')
    if data.get('code') not in (200, None):
        raise RuntimeError(data.get('message') or data.get('msg') or f'AList API 错误: {data}')
    return data


def walk_alist(config: dict, root_path: str) -> list:
    root_path = root_path.rstrip('/') or '/'
    found = []
    stack = [root_path]
    while stack:
        current = stack.pop()
        data = alist_request(config, '/api/fs/list', {
            'path': current,
            'password': '',
            'page': 1,
            'per_page': 0,
            'refresh': False,
        })
        content = ((data.get('data') or {}).get('content') or [])
        for item in content:
            name = item.get('name') or ''
            if not name:
                continue
            child = f"{current.rstrip('/')}/{name}" if current != '/' else f'/{name}'
            is_dir = bool(item.get('is_dir')) or int(item.get('type') or 0) == 1
            if is_dir:
                stack.append(child)
            elif Path(name).suffix.lower() in MEDIA_EXTS:
                found.append(child)
    return sorted(found)


def map_scan_to_media(scan_path: str, output_prefix: str, full_path: str) -> str:
    prefix = scan_path.rstrip('/')
    rel = full_path[len(prefix):].lstrip('/') if full_path.startswith(prefix + '/') else Path(full_path).name
    return f"{output_prefix.rstrip('/')}/{rel}".replace('//', '/')


def run_source(config: dict, src: dict):
    output_root = config.get('output_root', '/emby-strm')
    state = load_state()
    scan_path = src['scan_path']
    output_prefix = src['output_prefix']
    source_key = output_prefix
    resolved_mode = config.get('resolved_strm_mode', config.get('strm_mode', 'logical_path'))
    scan_mode = src.get('scan_mode', 'alist')
    print(f'扫描源目录: {scan_path}')
    print(f'STRM 输出前缀: {output_prefix}')
    print(f'扫描模式: {scan_mode}')
    print(f'本次 resolved_strm_mode: {resolved_mode}')
    try:
        files = walk_alist(config, scan_path)
    except Exception as e:
        print(f'跳过不可访问的 AList 目录: {scan_path} ({e})')
        return {
            'scan_path': scan_path,
            'output_prefix': output_prefix,
            'resolved_strm_mode': resolved_mode,
            'found': 0,
            'generated': 0,
            'skipped_existing_file': 0,
            'skipped_state_only': 0,
            'pruned_state_entries': 0,
            'missing_source': True,
            'error': str(e),
        }
    total_found = len(files)
    print(f'发现媒体文件 {total_found} 个')
    pruned_state_entries = prune_missing_state_entries(state, source_key, output_root)
    existing_state = set(state['sources'].get(source_key, {}).get('generated', []))
    incremental_only = config.get('scan', {}).get('incremental_only', True)
    generated = []
    skipped_existing_file = 0
    skipped_state_only = 0
    for full_path in files:
        media_path = map_scan_to_media(scan_path, output_prefix, full_path)
        target_file = normalize_output_path(output_root, media_path)
        if target_file.exists():
            skipped_existing_file += 1
            continue
        if incremental_only and media_path in existing_state and not target_file.exists():
            existing_state.discard(media_path)
        target_path = resolve_strm_target(config, media_path, full_path)
        generate_one(output_root, media_path, target_path)
        generated.append(media_path)
    record_generated(state, source_key, generated)
    save_state(state)
    summary = {
        'scan_path': scan_path,
        'output_prefix': output_prefix,
        'resolved_strm_mode': resolved_mode,
        'found': total_found,
        'generated': len(generated),
        'skipped_existing_file': skipped_existing_file,
        'skipped_state_only': skipped_state_only,
        'pruned_state_entries': pruned_state_entries,
    }
    print(f"统计: 发现 {total_found} 个，新增 {len(generated)} 个，跳过已存在文件 {skipped_existing_file} 个，状态跳过 {skipped_state_only} 个，清理失效状态 {pruned_state_entries} 个")
    return summary


def discover_sources(config: dict):
    discovered = []
    seen = set()
    for src in config.get('sources', []):
        key = (src.get('output_prefix'), src.get('scan_path'))
        if key in seen:
            continue
        seen.add(key)
        parts = src.get('output_prefix', '/').strip('/').split('/')
        discovered.append({
            'output_prefix': src.get('output_prefix'),
            'scan_path': src.get('scan_path'),
            'storage_root': parts[0] if len(parts) >= 1 else '',
            'category_root': parts[1] if len(parts) >= 2 else '',
        })
    return discovered


def choose_discovered_source(config: dict):
    discovered = discover_sources(config)
    if not discovered:
        print('未发现可扫描目录')
        return
    print('\n已配置的 AList 扫描目录：')
    for idx, item in enumerate(discovered, 1):
        print(f'{idx}. {item["output_prefix"]}')
    choice = input('请输入要扫描的编号（0 取消）: ').strip()
    if not choice or choice == '0':
        print('已取消')
        return
    try:
        idx = int(choice)
        if idx < 1 or idx > len(discovered):
            raise ValueError
    except ValueError:
        print('输入无效')
        return
    picked = discovered[idx - 1]
    print('当前使用 AList 目录扫描模式：直接扫描逻辑目录并生成对应 .strm。')
    run_source(config, picked)


def scan_specified_dir(config: dict):
    source_input = input('请输入需要扫描的 AList 目录（例如 /115/电影 或 /115/电影/泰坦尼克号）: ').strip()
    if not source_input:
        print('已取消')
        return
    src = build_source_from_input(config, source_input)
    print('当前使用 AList 目录扫描模式：直接扫描逻辑目录并生成对应 .strm。')
    run_source(config, src)


def cron_menu():
    print('\n定时扫描设定')
    print('1. 自动发现设置（待实现）')
    print('2. 自定义扫描设置（待实现）')
    print('当前版本已支持：按已配置的 AList 目录或手工输入逻辑目录扫描。')


def run_all_sources(config: dict):
    totals = {
        'sources': 0,
        'found': 0,
        'generated': 0,
        'skipped_existing_file': 0,
        'skipped_state_only': 0,
        'missing_sources': 0,
        'pruned_state_entries': 0,
        'resolved_strm_mode': config.get('resolved_strm_mode', config.get('strm_mode', 'logical_path')),
        'items': [],
    }
    for src in config.get('sources', []):
        summary = run_source(config, src)
        totals['sources'] += 1
        totals['found'] += summary['found']
        totals['generated'] += summary['generated']
        totals['skipped_existing_file'] += summary['skipped_existing_file']
        totals['skipped_state_only'] += summary['skipped_state_only']
        totals['pruned_state_entries'] += summary.get('pruned_state_entries', 0)
        totals['missing_sources'] += 1 if summary.get('missing_source') else 0
        totals['items'].append(summary)
    return totals


def build_source_from_input(config: dict, source_input: str):
    src = find_matching_source(config, source_input)
    if src:
        return src
    return {'scan_mode': 'alist', 'scan_path': source_input, 'output_prefix': source_input, 'library_type': 'custom', 'watch_depth': 1}


def parse_args():
    parser = argparse.ArgumentParser(description='xstrm scanner')
    parser.add_argument('--scan-all', action='store_true', help='扫描配置中的全部源')
    parser.add_argument('--scan-path', help='扫描指定 AList 目录，例如 /115/电影')
    parser.add_argument('--status-json', action='store_true', help='输出状态文件 JSON')
    parser.add_argument('--strm-mode', choices=['auto', 'logical_path', 'local_path'], help='本次运行覆盖 strm 输出模式')
    parser.add_argument('--profile-root', help='指定 emby2alist/nginx 根目录（应包含 conf.d/）')
    return parser.parse_args()


def main():
    args = parse_args()
    config = ensure_integrated_config(load_simple_yaml(CONFIG_PATH))
    if args.strm_mode:
        config['strm_mode'] = args.strm_mode
        config['resolved_strm_mode'] = args.strm_mode if args.strm_mode != 'auto' else config.get('resolved_strm_mode', 'logical_path')
    if args.profile_root:
        config.setdefault('emby2alist', {})['profile_root'] = args.profile_root
    save_yaml(CONFIG_PATH, config)

    if args.status_json:
        print(json.dumps(load_state(), ensure_ascii=False, indent=2))
        return
    if args.scan_all:
        result = run_all_sources(config)
        print(json.dumps({'mode': 'scan_all', **result}, ensure_ascii=False))
        return
    if args.scan_path:
        print('当前使用 AList 目录扫描模式：直接扫描逻辑目录并生成对应 .strm。')
        src = build_source_from_input(config, args.scan_path.strip())
        result = run_source(config, src)
        print(json.dumps({'mode': 'scan_path', **result}, ensure_ascii=False))
        return

    while True:
        print_main_menu()
        choice = input('请输入选项: ').strip()
        if choice == '1':
            choose_discovered_source(config)
        elif choice == '2':
            scan_specified_dir(config)
        elif choice == '3':
            show_integration(config)
        elif choice == '4':
            cron_menu()
        elif choice == '5':
            show_config(config)
        elif choice == '6':
            show_state()
        elif choice == '0':
            print('退出 XSTRM')
            break
        else:
            print('无效选项，请重试')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已取消')
        sys.exit(130)
    except Exception as e:
        print(f'执行失败: {e}')
        sys.exit(1)
