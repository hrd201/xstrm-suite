#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG1="$BASE_DIR/nginx/conf.d/config/constant-mount.js"
CFG2="$BASE_DIR/nginx/conf.d/config/constant-mount.runtime.js"
TARGET_ADDR_LINE='const alistAddr = "http://127.0.0.1:5244";'

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[ERR] missing command: $1" >&2
    exit 1
  }
}

need_cmd docker
need_cmd sed
need_cmd grep

if ! docker inspect alist >/dev/null 2>&1; then
  echo "[ERR] container 'alist' not found"
  exit 1
fi

ALIST_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' alist)"
if [[ -z "$ALIST_IP" ]]; then
  echo "[ERR] failed to detect alist container IP"
  exit 1
fi
TARGET_PUBLIC="http://$ALIST_IP:5244"

echo "[INFO] detected alist container IP: $ALIST_IP"
echo "[INFO] target alistPublicAddr: $TARGET_PUBLIC"

for f in "$CFG1" "$CFG2"; do
  if [[ ! -f "$f" ]]; then
    echo "[ERR] missing config file: $f"
    exit 1
  fi

  if ! grep -Fq "$TARGET_ADDR_LINE" "$f"; then
    echo "[WARN] expected alistAddr line not found in $f"
  fi

  sed -i -E "s#^const alistPublicAddr = \"http://[^\"]+\";#const alistPublicAddr = \"$TARGET_PUBLIC\";#" "$f"
  echo "[OK] updated $f"
done

if docker ps --format '{{.Names}}' | grep -qx 'xstrm-nginx'; then
  docker restart xstrm-nginx >/dev/null
  echo '[OK] restarted xstrm-nginx'
else
  echo '[WARN] container xstrm-nginx not found; skipped restart'
fi

echo '[DONE] alist/xstrm fix applied'
