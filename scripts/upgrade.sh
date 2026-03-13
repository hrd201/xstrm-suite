#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT="/opt/xstrm-suite"

mkdir -p "$INSTALL_ROOT"
rsync -a --delete --exclude '.git' --exclude '__pycache__' "$BASE_DIR/" "$INSTALL_ROOT/"
chmod +x "$INSTALL_ROOT/bin/xstrm" "$INSTALL_ROOT/bin/xstrm-admin" "$INSTALL_ROOT/scripts/"*.sh "$INSTALL_ROOT/scripts/strm_x.py" "$INSTALL_ROOT/scripts/admin_api.py"
ln -sf "$INSTALL_ROOT/bin/xstrm" /usr/local/bin/xstrm
ln -sf "$INSTALL_ROOT/bin/xstrm-admin" /usr/local/bin/xstrm-admin
if [ -f "$INSTALL_ROOT/services/xstrm-admin-api.service" ]; then
  cp "$INSTALL_ROOT/services/xstrm-admin-api.service" /etc/systemd/system/xstrm-admin-api.service
  sed -i 's#/opt/xstrm-suite#'$INSTALL_ROOT'#g' /etc/systemd/system/xstrm-admin-api.service
fi
echo '[done] xstrm-suite upgraded/synced'
