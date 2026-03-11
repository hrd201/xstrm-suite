#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="/opt/xstrm-suite"
BIN_LINK="/usr/local/bin/xstrm"
ADMIN_LINK="/usr/local/bin/xstrm-admin"
SERVICE_FILE="/etc/systemd/system/xstrm.service"

rm -f "$BIN_LINK"
rm -f "$ADMIN_LINK"
rm -f "$SERVICE_FILE"
if [ -d "$INSTALL_ROOT" ]; then
  rm -rf "$INSTALL_ROOT"
fi

echo '[done] xstrm-suite removed from system paths and install root'
