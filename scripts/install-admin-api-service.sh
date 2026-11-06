#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT="${INSTALL_ROOT:-/opt/xstrm-suite}"
if ! id xstrm >/dev/null 2>&1; then
  echo 'Run scripts/install.sh first to create the service user and writable directories.' >&2
  exit 1
fi
bash "$INSTALL_ROOT/scripts/install_python_requirements.sh" "$INSTALL_ROOT"
python3 - "$INSTALL_ROOT" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
Path('/etc/systemd/system/xstrm-admin-api.service').write_text((root/'services/xstrm-admin-api.service').read_text().replace('/opt/xstrm-suite',str(root)))
PY
systemctl daemon-reload
systemctl enable --now xstrm-admin-api.service
systemctl --no-pager --full status xstrm-admin-api.service
