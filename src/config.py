"""Configuration loading and inference."""
import json
import re
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'strm-sync.yaml'
EMBY2ALIST_CONSTANT = BASE_DIR / 'emby2alist' / 'conf.d' / 'constant.js'
EMBY2ALIST_MOUNT_CONFIG = BASE_DIR / 'emby2alist' / 'conf.d' / 'config' / 'constant-mount.js'
DEFAULT_NGINX_PROFILE_ROOT = BASE_DIR / 'emby2alist'

MEDIA_EXTS = {'.mp4', '.mkv', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.flv'}


def load_yaml(path: Path) -> dict:
    """Load YAML configuration file."""
    if not path.exists():
        return {}
    import yaml  # type: ignore
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict):
    """Save YAML configuration file."""
    import yaml  # type: ignore
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')


def load_config() -> dict:
    """Load configuration from strm-sync.yaml."""
    return load_yaml(CONFIG_PATH)


def save_config(config: dict):
    """Save configuration to strm-sync.yaml."""
    save_yaml(CONFIG_PATH, config)


def parse_js_string(text: str, name: str) -> Optional[str]:
    """Parse a string constant from JavaScript file."""
    m = re.search(rf'const\s+{re.escape(name)}\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else None


def parse_js_string_array(text: str, name: str) -> list:
    """Parse a string array from JavaScript file."""
    m = re.search(rf'const\s+{re.escape(name)}\s*=\s*\[([^\]]*)\]', text, re.S)
    if not m:
        return []
    return re.findall(r'"([^"]*)"', m.group(1))


def infer_emby2alist_settings() -> dict:
    """Infer emby2alist settings from constant files."""
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
    """Infer library type from output prefix."""
    normalized = output_prefix.lower()
    if any(token in normalized for token in ('电影', 'movie', 'movies', 'film', 'films')):
        return 'movie'
    return 'series'


def build_example_target(config: dict) -> str:
    """Build example target path."""
    return '/115/示例/样片.mkv'


def ensure_config(config: dict) -> dict:
    """Ensure configuration has all required fields with defaults."""
    config.setdefault('output_root', '/emby-strm')
    config.setdefault('state_file', str(BASE_DIR / 'data' / 'strm-sync-state.json'))
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
    """Normalize source configuration."""
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
    """Print configuration to stdout."""
    print(f'配置文件: {CONFIG_PATH}')
    print(json.dumps(config, ensure_ascii=False, indent=2))


def show_integration(config: dict):
    """Print integration settings to stdout."""
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
