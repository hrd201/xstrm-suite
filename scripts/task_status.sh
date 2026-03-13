#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "$BASE_DIR/scripts/task_lib.sh"

python3 - <<PY
import json
from pathlib import Path
base = Path(${BASE_DIR@Q})
status_file = Path(${STATUS_FILE@Q})
config_file = base / 'config' / 'strm-sync.yaml'
state_file = base / 'data' / 'strm-sync-state.json'
result = {
  'running': False,
  'task': None,
  'success': None,
  'message': '',
  'log_file': '',
  'started_at': None,
  'finished_at': None,
  'sources': [],
  'state_file': str(state_file),
}
if status_file.exists():
  try:
    result.update(json.loads(status_file.read_text(encoding='utf-8')))
  except Exception:
    pass
try:
  import yaml
  cfg = yaml.safe_load(config_file.read_text(encoding='utf-8')) or {}
  result['sources'] = [src.get('output_prefix') for src in cfg.get('sources', []) if isinstance(src, dict)]
except Exception:
  pass
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
