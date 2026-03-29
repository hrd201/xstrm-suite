"""STRM scanner - core scanning logic."""
import sys
import time
import random
from pathlib import Path
from typing import Dict, List, Optional

from .config import get_media_exts, normalize_source
from .state import (
    load_state,
    save_state,
    normalize_output_path,
    record_generated,
    prune_missing_state_entries,
)
from .alist_client import alist_request
from .generator import generate_one, resolve_strm_target, map_scan_to_media


def walk_alist(config: dict, root_path: str) -> List[str]:
    """Recursively walk AList directory and find media files.

    Args:
        config: Configuration dict with 'alist' settings
        root_path: Root path to start walking from

    Returns:
        List of absolute media file paths
    """
    root_path = root_path.rstrip('/') or '/'
    media_exts = get_media_exts(config)
    found = []
    stack = [root_path]
    scanned_dirs = 0
    while stack:
        current = stack.pop()
        print(f'[scan] dir#{scanned_dirs + 1} current={current} pending={len(stack)}', flush=True)
        data = alist_request(config, '/api/fs/list', {
            'path': current,
            'password': '',
            'page': 1,
            'per_page': 0,
            'refresh': False,
        })
        scanned_dirs += 1
        time.sleep(random.uniform(1.5, 3.5))
        if scanned_dirs % 10 == 0:
            time.sleep(random.uniform(5.0, 10.0))
        content = ((data.get('data') or {}).get('content') or [])
        for item in content:
            name = item.get('name') or ''
            if not name:
                continue
            child = f"{current.rstrip('/')}/{name}" if current != '/' else f'/{name}'
            is_dir = bool(item.get('is_dir')) or int(item.get('type') or 0) == 1
            if is_dir:
                stack.append(child)
            elif Path(name).suffix.lower() in media_exts:
                found.append(child)
    return sorted(found)


def find_matching_source(config: dict, source_input: str) -> Optional[dict]:
    """Find matching source from config by scan_path or output_prefix."""
    normalized = source_input.rstrip('/')
    for src in config.get('sources', []):
        if src.get('scan_path', '').rstrip('/') == normalized or src.get('output_prefix', '').rstrip('/') == normalized:
            return src
    return None


def logical_prefix_from_scan_path(scan_path: str, media_mount_paths: List[str]) -> str:
    """Map AList mount path to logical STRM prefix.

    Args:
        scan_path: AList scan path (e.g., /mnt/115/电影)
        media_mount_paths: List of mount paths (e.g., ['/mnt/115'])

    Returns:
        Logical prefix (e.g., /115/电影)
    """
    scan_path = (scan_path or '').rstrip('/') or '/'
    for mount in media_mount_paths or []:
        mount = (mount or '').rstrip('/')
        if mount and scan_path == mount:
            return '/'
        if mount and scan_path.startswith(mount + '/'):
            return scan_path[len(mount):] or '/'
    return scan_path


def build_source_from_input(config: dict, source_input: str) -> dict:
    """Build source dict from user input.

    Args:
        config: Full configuration
        source_input: User input path

    Returns:
        Source dict with scan_path, output_prefix, scan_mode, etc.
    """
    src = find_matching_source(config, source_input)
    if src:
        return src
    mount_paths = (config.get('emby2alist', {}) or {}).get('media_mount_path', []) or []
    output_prefix = logical_prefix_from_scan_path(source_input, mount_paths)
    return {
        'scan_mode': 'alist',
        'scan_path': source_input,
        'output_prefix': output_prefix,
        'library_type': 'custom',
        'watch_depth': 1,
    }


def run_source(config: dict, src: dict) -> dict:
    """Run scan on a single source.

    Args:
        config: Configuration dict
        src: Source dict with scan_path, output_prefix, etc.

    Returns:
        Summary dict with scan results
    """
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
        target_path = resolve_strm_target(config, media_path, full_path)

        if target_file.exists():
            try:
                current_content = target_file.read_text(encoding='utf-8').strip()
            except Exception:
                current_content = None
            if current_content == target_path:
                skipped_existing_file += 1
                continue

        if incremental_only and media_path in existing_state and not target_file.exists():
            skipped_state_only += 1
            continue

        if media_path in existing_state and not target_file.exists():
            existing_state.discard(media_path)

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


def discover_sources(config: dict) -> List[dict]:
    """Discover available sources from config."""
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


def run_all_sources(config: dict) -> dict:
    """Run scan on all configured sources.

    Args:
        config: Configuration dict

    Returns:
        Aggregated summary for all sources
    """
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
