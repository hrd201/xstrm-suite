#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/xstrm-suite}"
BACKUP_ROOT="$INSTALL_ROOT/data/upgrade-backups"

mkdir -p "$INSTALL_ROOT"
mkdir -p "$BACKUP_ROOT"
backup_file="$BACKUP_ROOT/config-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$backup_file" -C "$INSTALL_ROOT" \
  --ignore-failed-read \
  config/runtime.yaml config/strm-sync.yaml config/incremental-strm.json \
  nginx/conf.d/.htpasswd-xstrm-admin 2>/dev/null || true

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude 'data/' \
    --exclude 'config/runtime.yaml' \
    --exclude 'config/strm-sync.yaml' \
    --exclude 'config/incremental-strm.json' \
    --exclude 'config/cert/' \
    --exclude 'nginx/conf.d/.htpasswd-xstrm-admin' \
    --exclude '*.runtime.*' \
    "$BASE_DIR/" "$INSTALL_ROOT/"
else
  tar -C "$BASE_DIR" -cf - \
    --exclude='.git' --exclude='__pycache__' --exclude='data' \
    --exclude='config/runtime.yaml' --exclude='config/strm-sync.yaml' \
    --exclude='config/incremental-strm.json' --exclude='config/cert' \
    --exclude='nginx/conf.d/.htpasswd-xstrm-admin' --exclude='*.runtime.*' . \
    | tar -C "$INSTALL_ROOT" -xf -
fi
chmod +x "$INSTALL_ROOT/bin/xstrm" "$INSTALL_ROOT/bin/xstrm-admin" "$INSTALL_ROOT/scripts/"*.sh "$INSTALL_ROOT/scripts/strm_x.py" "$INSTALL_ROOT/scripts/admin_api.py"
ln -sf "$INSTALL_ROOT/bin/xstrm" /usr/local/bin/xstrm
ln -sf "$INSTALL_ROOT/bin/xstrm-admin" /usr/local/bin/xstrm-admin
if [ -f "$INSTALL_ROOT/services/xstrm-admin-api.service" ]; then
  cp "$INSTALL_ROOT/services/xstrm-admin-api.service" /etc/systemd/system/xstrm-admin-api.service
  sed -i 's#/opt/xstrm-suite#'$INSTALL_ROOT'#g' /etc/systemd/system/xstrm-admin-api.service
fi
chmod 600 "$INSTALL_ROOT/config/runtime.yaml" "$INSTALL_ROOT/config/strm-sync.yaml" "$INSTALL_ROOT/config/incremental-strm.json" 2>/dev/null || true
if id xstrm >/dev/null 2>&1; then
  chown xstrm:xstrm "$INSTALL_ROOT/config"
  chown xstrm:xstrm "$INSTALL_ROOT/config/runtime.yaml" "$INSTALL_ROOT/config/strm-sync.yaml" "$INSTALL_ROOT/config/incremental-strm.json" 2>/dev/null || true
fi
systemctl daemon-reload 2>/dev/null || true
systemctl restart xstrm-admin-api.service 2>/dev/null || true
echo "[done] xstrm-suite upgraded/synced; config backup: $backup_file"
