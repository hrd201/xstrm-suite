#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "$BASE_DIR/scripts/task_lib.sh"

TASK_NAME="scan_recent"
LOCK_DIR="$TASK_DIR/xstrm-write.lock"
LOG_FILE="$(task_log_path "$TASK_NAME")"
STARTED_AT="$(now_iso)"
RECENT_HOURS="${1:-24}"

if ! [[ "$RECENT_HOURS" =~ ^[0-9]+([.][0-9]+)?$ ]] || [[ "$RECENT_HOURS" == "0" ]]; then
  echo 'recent hours must be a positive number'
  exit 2
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  summary="任务正在执行中"
  emit_result "TASK_RUNNING" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 2
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

status_write "$TASK_NAME" true null "正在全盘查找最近 ${RECENT_HOURS} 小时新增或修改的项目" "$LOG_FILE" "$STARTED_AT" ""

if python3 "$BASE_DIR/scripts/strm_x.py" --scan-all --recent-hours "$RECENT_HOURS" >"$LOG_FILE" 2>&1; then
  summary="$(summary_from_log "$LOG_FILE")"
  FINISHED_AT="$(now_iso)"
  status_write "$TASK_NAME" false true "$summary" "$LOG_FILE" "$STARTED_AT" "$FINISHED_AT"
  emit_result "TASK_OK" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 0
else
  summary="$(tail -n 1 "$LOG_FILE" 2>/dev/null || echo '最近新增扫描失败')"
  FINISHED_AT="$(now_iso)"
  status_write "$TASK_NAME" false false "$summary" "$LOG_FILE" "$STARTED_AT" "$FINISHED_AT"
  emit_result "TASK_ERROR" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 1
fi
