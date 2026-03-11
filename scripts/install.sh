#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="/usr/local/bin"
TARGET_BIN="$BIN_DIR/xstrm"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_python() {
  if need_cmd python3; then
    echo "[ok] python3 already installed: $(python3 --version 2>/dev/null)"
    return
  fi
  echo "[info] python3 not found, installing..."
  if need_cmd apt-get; then
    apt-get update && apt-get install -y python3 python3-pip python3-yaml
  elif need_cmd dnf; then
    dnf install -y python3 python3-pip python3-PyYAML
  elif need_cmd yum; then
    yum install -y python3 python3-pip
    python3 -m pip install PyYAML
  else
    echo "[error] unsupported package manager, please install python3 manually"
    exit 1
  fi
}

install_pyyaml() {
  python3 - <<'PY' >/dev/null 2>&1
import yaml
print(yaml.__version__)
PY
  if [ $? -eq 0 ]; then
    echo "[ok] PyYAML already installed"
    return
  fi
  echo "[info] PyYAML not found, installing..."
  python3 -m pip install --upgrade pip PyYAML
}

install_bin() {
  chmod +x "$BASE_DIR/bin/xstrm" "$BASE_DIR/scripts/strm_x.py"
  ln -sf "$BASE_DIR/bin/xstrm" "$TARGET_BIN"
  echo "[ok] installed xstrm -> $TARGET_BIN"
}

main() {
  install_python
  install_pyyaml
  install_bin
  echo "[done] xstrm installed. Run: xstrm"
}

main "$@"
