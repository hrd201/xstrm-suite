#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "$BASE_DIR/scripts/task_lib.sh"

TASK_NAME="incremental_refresh"
LOCK_DIR="$TASK_DIR/xstrm-write.lock"
LOG_FILE="$(task_log_path "$TASK_NAME")"
STARTED_AT="$(now_iso)"
CONFIG_FILE="${XSTRM_INCREMENTAL_CONFIG:-$BASE_DIR/config/strm-sync.yaml}"
TARGET_PATH="${1:-}"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  summary="任务正在执行中"
  emit_result "TASK_RUNNING" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 2
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

if [[ ! -f "$CONFIG_FILE" ]]; then
  summary="缺少配置文件: $CONFIG_FILE"
  status_write "$TASK_NAME" false false "$summary" "$LOG_FILE" "$STARTED_AT" "$(now_iso)"
  emit_result "TASK_ERROR" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 1
fi

if [[ -n "$TARGET_PATH" ]]; then
  status_write "$TASK_NAME" true null "正在刷新指定目录: $TARGET_PATH" "$LOG_FILE" "$STARTED_AT" ""
  if ! python3 "$BASE_DIR/scripts/incremental_strm_refresh.py" --config "$CONFIG_FILE" \
    queue-dir "$TARGET_PATH" --reason web_manual >>"$LOG_FILE" 2>&1; then
    summary="指定目录加入队列失败"
    status_write "$TASK_NAME" false false "$summary" "$LOG_FILE" "$STARTED_AT" "$(now_iso)"
    emit_result "TASK_ERROR" "$TASK_NAME" "$LOG_FILE" "$summary"
    exit 1
  fi
else
  status_write "$TASK_NAME" true null "正在执行增量刷新" "$LOG_FILE" "$STARTED_AT" ""
fi

if python3 "$BASE_DIR/scripts/incremental_strm_refresh.py" --config "$CONFIG_FILE" run-once >>"$LOG_FILE" 2>&1; then
  summary="$(tail -n 20 "$LOG_FILE" | tr '\n' ' ' | sed -E 's/[[:space:]]+/ /g')"
  FINISHED_AT="$(now_iso)"
  status_write "$TASK_NAME" false true "$summary" "$LOG_FILE" "$STARTED_AT" "$FINISHED_AT"
  emit_result "TASK_OK" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 0
else
  summary="增量刷新存在失败目录，详情见日志: $LOG_FILE"
  FINISHED_AT="$(now_iso)"
  status_write "$TASK_NAME" false false "$summary" "$LOG_FILE" "$STARTED_AT" "$FINISHED_AT"
  emit_result "TASK_ERROR" "$TASK_NAME" "$LOG_FILE" "$summary"
  exit 1
fi
