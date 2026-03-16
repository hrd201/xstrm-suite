"""State management for STRM generation."""
import json
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / 'data' / 'strm-sync-state.json'


def load_state() -> dict:
    """Load state from JSON file."""
    if not STATE_PATH.exists():
        return {'version': 1, 'sources': {}}
    return json.loads(STATE_PATH.read_text(encoding='utf-8'))


def save_state(state: dict):
    """Save state to JSON file."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def show_state():
    """Print current state to stdout."""
    print(f'状态文件: {STATE_PATH}')
    print(json.dumps(load_state(), ensure_ascii=False, indent=2))


def normalize_output_path(output_root: str, media_path: str) -> Path:
    """Normalize output .strm file path."""
    relative = media_path.lstrip('/')
    return Path(output_root) / Path(relative).with_suffix('.strm')


def record_generated(state: dict, source_key: str, media_paths: list):
    """Record generated .strm files in state."""
    bucket = state['sources'].setdefault(source_key, {'generated': []})
    existing = set(bucket.get('generated', []))
    for media in media_paths:
        if media not in existing:
            bucket['generated'].append(media)


def prune_missing_state_entries(state: dict, source_key: str, output_root: str) -> int:
    """Remove state entries where .strm files no longer exist."""
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
