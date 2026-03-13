#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "$BASE_DIR/scripts/task_lib.sh"

TASK_NAME="rebuild_all"
LOCK_DIR="$TASK_DIR/${TASK_NAME}.lock"
LOG_FILE="$(task_log_path "$TASK_NAME")"
STARTED_AT="$(now_iso)"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  summary="全量重建任务正在执行中"
  emit_result "TASK_RUNNING" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 2
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

status_write "$TASK_NAME" true null "正在全量重建 STRM" "$LOG_FILE" "$STARTED_AT" ""

OUTPUT_ROOT=$(python3 - <<PY
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path(${BASE_DIR@Q}).joinpath('config/strm-sync.yaml').read_text(encoding='utf-8')) or {}
print(cfg.get('output_root', '/emby-strm'))
PY
)

{
  echo "[rebuild] output_root=$OUTPUT_ROOT"
  if [ -d "$OUTPUT_ROOT" ]; then
    find "$OUTPUT_ROOT" -type f -name '*.strm' -delete
    echo "[rebuild] 已清理旧 strm 文件"
  else
    echo "[rebuild] 输出目录不存在，跳过清理"
  fi
  python3 - <<PY
import json
from pathlib import Path
state = Path(${BASE_DIR@Q}) / 'data' / 'strm-sync-state.json'
state.parent.mkdir(parents=True, exist_ok=True)
state.write_text(json.dumps({"version": 1, "sources": {}}, ensure_ascii=False, indent=2), encoding='utf-8')
print('[rebuild] 已重置状态文件')
PY
  python3 "$BASE_DIR/scripts/strm_x.py" --scan-all
} >"$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
  summary="$(summary_from_log "$LOG_FILE")"
  FINISHED_AT="$(now_iso)"
  status_write "$TASK_NAME" false true "$summary" "$LOG_FILE" "$STARTED_AT" "$FINISHED_AT"
  emit_result "TASK_OK" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 0
fi

summary="$(tail -n 1 "$LOG_FILE" 2>/dev/null || echo '全量重建失败')"
FINISHED_AT="$(now_iso)"
status_write "$TASK_NAME" false false "$summary" "$LOG_FILE" "$STARTED_AT" "$FINISHED_AT"
emit_result "TASK_ERROR" "$TASK_NAME" "$LOG_FILE" "$summary"
exit 1
