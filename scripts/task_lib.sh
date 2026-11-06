#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$BASE_DIR/.venv/bin/python3" ]]; then export PATH="$BASE_DIR/.venv/bin:$PATH"; fi
TASK_DIR="$BASE_DIR/data/tasks"
LOG_DIR="$TASK_DIR/logs"
STATUS_FILE="$TASK_DIR/status.json"
mkdir -p "$LOG_DIR"

# Kernel-owned lock survives neither process exit nor container restart. Child
# scanners inherit FD 9, so a killed parent cannot allow overlapping writers.
task_lock() {
  exec 9>"$TASK_DIR/xstrm-write.flock"
  if ! flock -n 9; then
    emit_result "TASK_RUNNING" "$TASK_NAME" "$LOG_FILE" "有写入任务正在执行"
    exit 2
  fi
}

now_iso() {
  date -Iseconds
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

task_log_path() {
  local task_name="$1"
  printf '%s/%s-%s.log\n' "$LOG_DIR" "$task_name" "$(date +%Y%m%d-%H%M%S)"
}

status_write() {
  local task_name="$1"
  local running="$2"
  local success="$3"
  local message="$4"
  local log_file="$5"
  local started_at="$6"
  local finished_at="$7"
  python3 - "$STATUS_FILE" "$task_name" "$running" "$success" "$message" "$log_file" "$started_at" "$finished_at" "${XSTRM_RUN_ID:-}" <<'PY'
import json
import sys
from pathlib import Path

def parse_value(v):
    if v == 'true':
        return True
    if v == 'false':
        return False
    if v == 'null':
        return None
    return v

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
data = {
  "task": sys.argv[2],
  "running": parse_value(sys.argv[3]),
  "success": parse_value(sys.argv[4]),
  "message": sys.argv[5],
  "log_file": sys.argv[6],
  "started_at": sys.argv[7],
  "finished_at": sys.argv[8],
  "run_id": sys.argv[9],
}
temporary = path.with_suffix('.tmp')
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
temporary.replace(path)
PY
}

summary_from_log() {
  local log_file="$1"
  python3 - "$log_file" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print("")
    raise SystemExit(0)
summary = ""
for line in p.read_text(encoding='utf-8', errors='ignore').splitlines()[::-1]:
    line = line.strip()
    if not line:
        continue
    if line.startswith('{') and line.endswith('}'):
        try:
            data = json.loads(line)
            resolved_mode = data.get('resolved_strm_mode')
            summary = f"发现 {data.get('found', 0)} 个，新增 {data.get('generated', 0)} 个，跳过已存在文件 {data.get('skipped_existing_file', 0)} 个，状态跳过 {data.get('skipped_state_only', 0)} 个"
            if resolved_mode:
                summary += f"，resolved_strm_mode={resolved_mode}"
            break
        except Exception:
            pass
    if line.startswith('统计:'):
        summary = line
        break
    if not summary:
        summary = line
print(summary)
PY
}

emit_result() {
  local result="$1"
  local task_name="$2"
  local log_file="$3"
  local summary="$4"
  printf '%s\n' "$result"
  printf 'TASK_NAME=%s\n' "$task_name"
  printf 'LOG_FILE=%s\n' "$log_file"
  printf 'SUMMARY=%s\n' "$summary"
}
