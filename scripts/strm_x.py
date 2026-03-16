#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

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
        return {"version": 1, "sources": {}}
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
    body = m.group(1)
    return re.findall(r'"([^"]*)"', body)


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
    result['defaultSources'] = infer_default_sources_from_mounts(result['mediaMountPath'])
    pro_path = DEFAULT_NGINX_PROFILE_ROOT / 'conf.d' / 'config' / 'constant-pro.js'
    if pro_path.exists():
        pro_text = pro_path.read_text(encoding='utf-8')
        if '"/115/"' in pro_text and '/emby-strm/115/' in pro_text:
            result['preferredStrmMode'] = 'logical_path'
        elif result['mediaMountPath']:
            result['preferredStrmMode'] = 'local_path'
    return result




def infer_library_type(output_prefix: str) -> str:
    normalized = output_prefix.lower()
    if any(token in normalized for token in ('电影', 'movie', 'movies', 'film', 'films')):
        return 'movie'
    return 'series'


def infer_default_sources_from_mounts(media_mount_paths: list) -> list:
    discovered = []
    seen = set()
    for mount in media_mount_paths:
        if not mount:
            continue
        mount_root = Path(mount)
        if not mount_root.exists():
            continue
        for storage in sorted([p for p in mount_root.iterdir() if p.is_dir()]):
            for category in sorted([p for p in storage.iterdir() if p.is_dir()]):
                output_prefix = f'/{storage.name}/{category.name}'
                if output_prefix in seen:
                    continue
                seen.add(output_prefix)
                discovered.append({
                    'output_prefix': output_prefix,
                    'scan_path': str(category),
                    'library_type': infer_library_type(output_prefix),
                    'watch_depth': 1,
                })
    return discovered


def build_example_target(config: dict) -> str:
    mode = config.get('resolved_strm_mode', config.get('strm_mode', 'logical_path'))
    mount_paths = config.get('emby2alist', {}).get('media_mount_path', [])
    base = '/115/示例/样片.mkv'
    if mode == 'local_path' and mount_paths:
        return f"{mount_paths[0].rstrip('/')}" + base
    return base

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
    if not sources:
        sources.extend(inferred.get('defaultSources', []))

    for src in sources:
        if not src.get('library_type'):
            src['library_type'] = infer_library_type(src.get('output_prefix', src.get('scan_path', '')))
        src.setdefault('watch_depth', 1)
        normalize_source(src, emby2alist.get('media_mount_path', []))
    return config


def normalize_source(src: dict, media_mount_paths: list):
    if src.get('path') and not src.get('output_prefix'):
        src['output_prefix'] = src['path']
    output_prefix = src.get('output_prefix', '').rstrip('/')
    if output_prefix and not src.get('scan_path'):
        scan_path = output_prefix
        for mount in media_mount_paths:
            if mount:
                scan_path = f"{mount.rstrip('/')}{output_prefix}"
                break
        src['scan_path'] = scan_path
    if src.get('scan_path') and not src.get('output_prefix'):
        scan_path = src['scan_path']
        output = scan_path
        for mount in media_mount_paths:
            if mount and scan_path.startswith(mount.rstrip('/') + '/'):
                output = scan_path[len(mount.rstrip('/')):]
                break
        src['output_prefix'] = output


def print_main_menu():
    print('\nXSTRM 菜单')
    print('1. 从已发现目录中选择扫描')
    print('2. 扫描指定目录')
    print('3. 查看同源配置')
    print('4. 定时扫描设定')
    print('5. 查看当前配置')
    print('6. 查看状态文件')
    print('0. 退出')


def show_config(config: dict):
    print(f'配置文件: {CONFIG_PATH}')
    print(json.dumps(config, ensure_ascii=False, indent=2))


def show_state():
    print(f'状态文件: {STATE_PATH}')
    print(json.dumps(load_state(), ensure_ascii=False, indent=2))


def show_integration(config: dict):
    print('emby2alist 同源配置：')
    print(json.dumps({
        'profile_root': config.get('emby2alist', {}).get('profile_root'),
        'media_mount_path': config.get('emby2alist', {}).get('media_mount_path', []),
        'alist': config.get('alist', {}),
        'strm_mode': config.get('strm_mode'),
        'resolved_strm_mode': config.get('resolved_strm_mode'),
        'sources': config.get('sources', []),
        'expected_target_example': build_example_target(config),
    }, ensure_ascii=False, indent=2))


def normalize_output_path(output_root: str, media_path: str) -> Path:
    relative = media_path.lstrip('/')
    return Path(output_root) / Path(relative).with_suffix('.strm')


def resolve_strm_target(config: dict, media_path: str, full_path: str) -> str:
    mode = config.get('resolved_strm_mode', config.get('strm_mode', 'logical_path'))
    if mode == 'local_path':
        return full_path
    return media_path


def generate_one(output_root: str, media_path: str, target_path: str) -> Path:
    out = normalize_output_path(output_root, media_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(target_path, encoding='utf-8')
    print(f'已生成: {out}')
    return out


def strm_exists(output_root: str, media_path: str) -> bool:
    return normalize_output_path(output_root, media_path).exists()


def walk_local(root_path: str) -> list:
    root = Path(root_path)
    if not root.exists():
        raise RuntimeError(f'扫描目录不存在: {root_path}')
    found = []
    for p in root.rglob('*'):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS:
            found.append(str(p))
    return sorted(found)


def map_scan_to_media(scan_path: str, output_prefix: str, full_path: str) -> str:
    rel = str(Path(full_path).relative_to(Path(scan_path)))
    return f"{output_prefix.rstrip('/')}/{rel}".replace('//', '/')


def record_generated(state: dict, source_key: str, media_paths: list):
    bucket = state['sources'].setdefault(source_key, {'generated': []})
    existing = set(bucket.get('generated', []))
    for media in media_paths:
        if media not in existing:
            bucket['generated'].append(media)


def find_matching_source(config: dict, source_input: str):
    normalized = source_input.rstrip('/')
    for src in config.get('sources', []):
        if src.get('scan_path', '').rstrip('/') == normalized or src.get('output_prefix', '').rstrip('/') == normalized:
            return src
    return None


def run_source(config: dict, src: dict):
    output_root = config.get('output_root', '/emby-strm')
    state = load_state()
    scan_path = src['scan_path']
    output_prefix = src['output_prefix']
    source_key = output_prefix
    resolved_mode = config.get('resolved_strm_mode', config.get('strm_mode', 'logical_path'))
    print(f'扫描源目录: {scan_path}')
    print(f'STRM 输出前缀: {output_prefix}')
    print(f'本次 resolved_strm_mode: {resolved_mode}')
    if not Path(scan_path).exists():
        print(f'跳过不存在的扫描目录: {scan_path}')
        return {
            'scan_path': scan_path,
            'output_prefix': output_prefix,
            'resolved_strm_mode': resolved_mode,
            'found': 0,
            'generated': 0,
            'skipped_existing_file': 0,
            'skipped_state_only': 0,
            'missing_source': True,
        }
    files = walk_local(scan_path)
    total_found = len(files)
    print(f'发现媒体文件 {total_found} 个')
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
        # 以最终 .strm 文件是否存在为准，而不是只看历史状态。
        # 这样即使状态文件里记过“已生成”，但目标 .strm 被手工删除/丢失，
        # 也会自动补回，而不是被 incremental_only 误跳过。
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
    mount_paths = config.get('emby2alist', {}).get('media_mount_path', [])
    if mount_paths:
        mount_root = Path(mount_paths[0])
        if mount_root.exists():
            for storage in sorted([p for p in mount_root.iterdir() if p.is_dir()]):
                for category in sorted([p for p in storage.iterdir() if p.is_dir()]):
                    output_prefix = f'/{storage.name}/{category.name}'
                    scan_path = str(category)
                    key = (output_prefix, scan_path)
                    if key not in seen:
                        seen.add(key)
                        discovered.append({
                            'output_prefix': output_prefix,
                            'scan_path': scan_path,
                            'storage_root': storage.name,
                            'category_root': category.name,
                        })
    for src in config.get('sources', []):
        key = (src.get('output_prefix'), src.get('scan_path'))
        if key not in seen:
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
    print('\n已发现目录（默认只列两层，不显示 /mnt）：')
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
    print('当前使用 emby2alist 同源整合模式：展示层隐藏 /mnt，内部扫描挂载目录。')
    run_source(config, picked)


def scan_specified_dir(config: dict):
    source_input = input('请输入需要扫描的目录（可填 scan_path 或 output_prefix，例如 /mnt/115/电影/泰坦尼克号 或 /115/电影）: ').strip()
    if not source_input:
        print('已取消')
        return
    src = build_source_from_input(config, source_input)
    print('当前使用 emby2alist 同源整合模式：扫描挂载目录，输出去挂载前缀后的媒体路径。')
    run_source(config, src)


def cron_menu():
    print('\n定时扫描设定')
    print('1. 自动发现设置（待实现）')
    print('2. 自定义扫描设置（待实现）')
    print('当前版本已支持：先发现两层目录，再按编号选择扫描。')


def run_all_sources(config: dict):
    totals = {
        'sources': 0,
        'found': 0,
        'generated': 0,
        'skipped_existing_file': 0,
        'skipped_state_only': 0,
        'missing_sources': 0,
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
        totals['missing_sources'] += 1 if summary.get('missing_source') else 0
        totals['items'].append(summary)
    return totals


def build_source_from_input(config: dict, source_input: str):
    src = find_matching_source(config, source_input)
    if src:
        return src
    if source_input.startswith('/mnt/'):
        mount_paths = config.get('emby2alist', {}).get('media_mount_path', [])
        output_prefix = source_input
        for mount in mount_paths:
            prefix = mount.rstrip('/') + '/'
            if source_input.startswith(prefix):
                output_prefix = '/' + source_input[len(prefix):]
                break
        return {'scan_path': source_input, 'output_prefix': output_prefix, 'library_type': 'custom', 'watch_depth': 1}
    mount_paths = config.get('emby2alist', {}).get('media_mount_path', [])
    scan_path = source_input
    for mount in mount_paths:
        scan_path = mount.rstrip('/') + source_input
        break
    return {'scan_path': scan_path, 'output_prefix': source_input, 'library_type': 'custom', 'watch_depth': 1}


def parse_args():
    parser = argparse.ArgumentParser(description='xstrm scanner')
    parser.add_argument('--scan-all', action='store_true', help='扫描配置中的全部源')
    parser.add_argument('--scan-path', help='扫描指定目录，可填 scan_path 或 output_prefix')
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
        print('当前使用 emby2alist 同源整合模式：扫描挂载目录，输出去挂载前缀后的媒体路径。')
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
