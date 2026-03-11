#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT="/opt/xstrm-suite"

mkdir -p "$INSTALL_ROOT"
rsync -a --delete --exclude '.git' --exclude '__pycache__' "$BASE_DIR/" "$INSTALL_ROOT/"
chmod +x "$INSTALL_ROOT/bin/xstrm" "$INSTALL_ROOT/bin/xstrm-admin" "$INSTALL_ROOT/scripts/"*.sh "$INSTALL_ROOT/scripts/strm_x.py"
ln -sf "$INSTALL_ROOT/bin/xstrm" /usr/local/bin/xstrm
ln -sf "$INSTALL_ROOT/bin/xstrm-admin" /usr/local/bin/xstrm-admin
echo '[done] xstrm-suite upgraded/synced'
