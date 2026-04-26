#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG1="$BASE_DIR/nginx/conf.d/config/constant-mount.js"
CFG2="$BASE_DIR/nginx/conf.d/config/constant-mount.runtime.js"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[ERR] missing command: $1" >&2
    exit 1
  }
}

need_cmd docker
need_cmd grep
need_cmd sed

if ! docker inspect alist >/dev/null 2>&1; then
  echo "[ERR] container 'alist' not found"
  exit 1
fi

ALIST_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' alist)"
PORTS_LINE="$(docker ps --format '{{.Names}}\t{{.Ports}}' | awk -F '\t' '$1=="alist"{print $2}')"
CFG1_PUBLIC="$(grep -E '^const alistPublicAddr = ' "$CFG1" || true)"
CFG2_PUBLIC="$(grep -E '^const alistPublicAddr = ' "$CFG2" || true)"
CFG1_ADDR="$(grep -E '^const alistAddr = ' "$CFG1" || true)"
CFG2_ADDR="$(grep -E '^const alistAddr = ' "$CFG2" || true)"

printf 'alist ip: %s\n' "$ALIST_IP"
printf 'alist ports: %s\n' "$PORTS_LINE"
printf 'constant-mount.js alistAddr: %s\n' "$CFG1_ADDR"
printf 'constant-mount.js alistPublicAddr: %s\n' "$CFG1_PUBLIC"
printf 'constant-mount.runtime.js alistAddr: %s\n' "$CFG2_ADDR"
printf 'constant-mount.runtime.js alistPublicAddr: %s\n' "$CFG2_PUBLIC"

if echo "$PORTS_LINE" | grep -q '0.0.0.0:5244'; then
  echo '[WARN] alist 5244 is publicly exposed on 0.0.0.0'
else
  echo '[OK] alist 5244 is not publicly exposed on 0.0.0.0'
fi

if echo "$CFG1_PUBLIC $CFG2_PUBLIC" | grep -q "$ALIST_IP"; then
  echo '[OK] alistPublicAddr appears aligned with current alist container IP'
else
  echo '[WARN] alistPublicAddr does not match current alist container IP'
fi
