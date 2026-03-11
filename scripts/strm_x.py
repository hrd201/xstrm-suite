#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'strm-sync.yaml'
STATE_PATH = BASE_DIR / 'data' / 'strm-sync-state.json'
EMBY2ALIST_CONSTANT = BASE_DIR / 'emby2alist' / 'conf.d' / 'constant.js'
EMBY2ALIST_MOUNT_CONFIG = BASE_DIR / 'emby2alist' / 'conf.d' / 'config' / 'constant-mount.js'
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
    }
    if EMBY2ALIST_CONSTANT.exists():
        text = EMBY2ALIST_CONSTANT.read_text(encoding='utf-8')
        result['mediaMountPath'] = parse_js_string_array(text, 'mediaMountPath')
    if EMBY2ALIST_MOUNT_CONFIG.exists():
        text = EMBY2ALIST_MOUNT_CONFIG.read_text(encoding='utf-8')
        result['alistAddr'] = parse_js_string(text, 'alistAddr')
        result['alistToken'] = parse_js_string(text, 'alistToken')
        result['alistPublicAddr'] = parse_js_string(text, 'alistPublicAddr')
    return result


def ensure_integrated_config(config: dict) -> dict:
    config.setdefault('output_root', '/emby-strm')
    config.setdefault('state_file', str(STATE_PATH))
    config.setdefault('mode', 'mirror')
    config.setdefault('scan', {})
    config['scan'].setdefault('incremental_only', True)
    config['scan'].setdefault('include_ext', sorted(MEDIA_EXTS))
    config.setdefault('emby2alist', {})
    config.setdefault('alist', {})

    inferred = infer_emby2alist_settings()
    emby2alist = config['emby2alist']
    if not emby2alist.get('media_mount_path'):
        emby2alist['media_mount_path'] = inferred.get('mediaMountPath', [])

    if not config['alist'].get('base_url') and inferred.get('alistAddr'):
        config['alist']['base_url'] = inferred['alistAddr']
    if not config['alist'].get('token') and inferred.get('alistToken'):
        config['alist']['token'] = inferred['alistToken']
    if not config['alist'].get('public_url') and inferred.get('alistPublicAddr'):
        config['alist']['public_url'] = inferred['alistPublicAddr']

    sources = config.setdefault('sources', [])
    if not sources:
        sources.extend([
            {'output_prefix': '/115/电影', 'library_type': 'movie', 'watch_depth': 1},
            {'output_prefix': '/115/剧集', 'library_type': 'series', 'watch_depth': 1},
            {'output_prefix': '/115/动画', 'library_type': 'series', 'watch_depth': 1},
        ])

    for src in sources:
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
        'media_mount_path': config.get('emby2alist', {}).get('media_mount_path', []),
        'alist': config.get('alist', {}),
        'sources': config.get('sources', []),
    }, ensure_ascii=False, indent=2))


def normalize_output_path(output_root: str, media_path: str) -> Path:
    relative = media_path.lstrip('/')
    return Path(output_root) / Path(relative).with_suffix('.strm')


def generate_one(output_root: str, media_path: str) -> Path:
    out = normalize_output_path(output_root, media_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(media_path, encoding='utf-8')
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
    print(f'扫描源目录: {scan_path}')
    print(f'STRM 输出前缀: {output_prefix}')
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
        if strm_exists(output_root, media_path):
            skipped_existing_file += 1
            continue
        if incremental_only and media_path in existing_state:
            skipped_state_only += 1
            continue
        generate_one(output_root, media_path)
        generated.append(media_path)
    record_generated(state, source_key, generated)
    save_state(state)
    print(f'统计: 发现 {total_found} 个，新增 {len(generated)} 个，跳过已存在文件 {skipped_existing_file} 个，状态跳过 {skipped_state_only} 个')


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
    src = find_matching_source(config, source_input)
    if not src:
        if source_input.startswith('/mnt/'):
            mount_paths = config.get('emby2alist', {}).get('media_mount_path', [])
            output_prefix = source_input
            for mount in mount_paths:
                prefix = mount.rstrip('/') + '/'
                if source_input.startswith(prefix):
                    output_prefix = '/' + source_input[len(prefix):]
                    break
            src = {'scan_path': source_input, 'output_prefix': output_prefix, 'library_type': 'custom', 'watch_depth': 1}
        else:
            mount_paths = config.get('emby2alist', {}).get('media_mount_path', [])
            scan_path = source_input
            for mount in mount_paths:
                scan_path = mount.rstrip('/') + source_input
                break
            src = {'scan_path': scan_path, 'output_prefix': source_input, 'library_type': 'custom', 'watch_depth': 1}
    print('当前使用 emby2alist 同源整合模式：扫描挂载目录，输出去挂载前缀后的媒体路径。')
    run_source(config, src)


def cron_menu():
    print('\n定时扫描设定')
    print('1. 自动发现设置（待实现）')
    print('2. 自定义扫描设置（待实现）')
    print('当前版本已支持：先发现两层目录，再按编号选择扫描。')


def main():
    config = ensure_integrated_config(load_simple_yaml(CONFIG_PATH))
    save_yaml(CONFIG_PATH, config)
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
