#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="/opt/xstrm-suite"
BIN_LINK="/usr/local/bin/xstrm"
ADMIN_LINK="/usr/local/bin/xstrm-admin"
SERVICE_FILE="/etc/systemd/system/xstrm.service"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

echo '[repair] checking python3'
if ! need_cmd python3; then
  echo '[repair] python3 missing, please run bootstrap.sh first'
  exit 1
fi

echo '[repair] checking install root'
if [ ! -d "$INSTALL_ROOT" ]; then
  echo '[repair] install root missing: '$INSTALL_ROOT
  exit 1
fi

echo '[repair] fixing command link'
ln -sf "$INSTALL_ROOT/bin/xstrm" "$BIN_LINK"
ln -sf "$INSTALL_ROOT/bin/xstrm-admin" "$ADMIN_LINK"

echo '[repair] fixing executable bits'
chmod +x "$INSTALL_ROOT/bin/xstrm" "$INSTALL_ROOT/bin/xstrm-admin" "$INSTALL_ROOT/scripts/"*.sh "$INSTALL_ROOT/scripts/strm_x.py" "$INSTALL_ROOT/scripts/render_runtime.py"

if [ -f "$INSTALL_ROOT/scripts/render_runtime.py" ]; then
  echo '[repair] rendering runtime-derived config files'
  python3 "$INSTALL_ROOT/scripts/render_runtime.py"
fi
if [ -f "$INSTALL_ROOT/scripts/apply_runtime.py" ]; then
  echo '[repair] applying runtime into live config files'
  python3 "$INSTALL_ROOT/scripts/apply_runtime.py"
fi

if [ -f "$INSTALL_ROOT/services/xstrm.service" ]; then
  cp "$INSTALL_ROOT/services/xstrm.service" "$SERVICE_FILE"
  sed -i 's#/opt/xstrm-suite#'$INSTALL_ROOT'#g' "$SERVICE_FILE"
  echo '[repair] refreshed xstrm.service template'
fi

echo '[repair] done'
