#!/usr/bin/env bash
# Isolate host dependencies from distro-managed Python (including PEP 668).
set -euo pipefail
umask 022
root=${1:-$(cd "$(dirname "$0")/.." && pwd)}
python_bin=${XSTRM_PYTHON_BIN:-python3}
"$python_bin" -c 'import sys; sys.exit("Python 3.10 or newer is required") if sys.version_info < (3,10) else None'
if [[ ! -x "$root/.venv/bin/python3" ]]; then
  "$python_bin" -m venv "$root/.venv" || {
    echo 'Install your distribution python3-venv package, then retry.' >&2
    exit 1
  }
fi
"$root/.venv/bin/python3" -m pip install --find-links="$root/deploy/wheels" -r "$root/requirements.txt"
