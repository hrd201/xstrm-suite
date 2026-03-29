#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def parse_js_string(text: str, name: str):
    m = re.search(rf'const\s+{re.escape(name)}\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else None


def parse_js_string_array(text: str, name: str):
    m = re.search(rf'const\s+{re.escape(name)}\s*=\s*\[([^\]]*)\]', text, re.S)
    if not m:
        return []
    return re.findall(r'"([^"]*)"', m.group(1))


def parse_client_self_rule(text: str):
    m = re.search(r'const\s+clientSelfAlistRule\s*=\s*\[(.*?)\];', text, re.S)
    if not m:
        return []
    body = m.group(1)
    return [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith('//')]


def infer_preferred_mode(media_mount_paths: list[str], media_path_mapping_lines: list[str]) -> str:
    for line in media_path_mapping_lines:
        if '"/115/"' in line and '/emby-strm/115/' in line:
            return 'logical_path'
    if media_mount_paths:
        return 'local_path'
    return 'logical_path'


def load_profile(root: Path) -> dict:
    conf_d = root / 'conf.d'
    constant_js = read_text(conf_d / 'constant.js')
    mount_js = read_text(conf_d / 'config' / 'constant-mount.js')
    pro_js = read_text(conf_d / 'config' / 'constant-pro.js')

    media_mount_path = parse_js_string_array(constant_js, 'mediaMountPath')
    alist_addr = parse_js_string(mount_js, 'alistAddr')
    alist_token = parse_js_string(mount_js, 'alistToken')
    alist_public_addr = parse_js_string(mount_js, 'alistPublicAddr')

    m = re.search(r'const\s+mediaPathMapping\s*=\s*\[(.*?)\];', pro_js, re.S)
    media_path_mapping = []
    if m:
        media_path_mapping = [line.strip().rstrip(',') for line in m.group(1).splitlines() if line.strip() and not line.strip().startswith('//')]

    profile = {
        'source_root': str(root),
        'mediaMountPath': media_mount_path,
        'alistAddr': alist_addr,
        'alistToken': alist_token,
        'alistPublicAddr': alist_public_addr,
        'clientSelfAlistRule': parse_client_self_rule(mount_js),
        'mediaPathMapping': media_path_mapping,
    }
    profile['preferredStrmMode'] = infer_preferred_mode(media_mount_path, media_path_mapping)
    return profile


def parse_args():
    parser = argparse.ArgumentParser(description='Load emby2alist nginx profile')
    parser.add_argument('--root', default='/home/hrd/.openclaw/workspace/projects/xstrm-suite/nginx', help='nginx root containing conf.d/')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    print(json.dumps(load_profile(Path(args.root)), ensure_ascii=False, indent=2))
