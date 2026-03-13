#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT="/opt/xstrm-suite"
BIN_LINK="/usr/local/bin/xstrm"
ADMIN_LINK="/usr/local/bin/xstrm-admin"
SERVICE_DIR="/etc/systemd/system"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

log() {
  printf '[xstrm-bootstrap] %s\n' "$*"
}

install_python() {
  if need_cmd python3; then
    log "python3 already installed: $(python3 --version 2>/dev/null)"
  else
    log "python3 not found, installing"
    if need_cmd apt-get; then
      apt-get update && apt-get install -y python3 python3-pip python3-yaml
    elif need_cmd dnf; then
      dnf install -y python3 python3-pip python3-PyYAML
    elif need_cmd yum; then
      yum install -y python3 python3-pip || true
      python3 -m pip install PyYAML
    else
      log "unsupported package manager; install python3 manually"
      exit 1
    fi
  fi

  if python3 - <<'PY' >/dev/null 2>&1
import yaml
PY
  then
    log "PyYAML already installed"
  else
    log "installing PyYAML"
    python3 -m pip install --upgrade pip PyYAML
  fi
}

check_docker() {
  if need_cmd docker; then
    log "docker found: $(docker --version 2>/dev/null)"
  else
    log "docker not found. Please install docker first for the default nginx/emby2alist runtime mode."
    exit 1
  fi
  if docker compose version >/dev/null 2>&1; then
    log "docker compose plugin found"
  elif need_cmd docker-compose; then
    log "docker-compose found"
  else
    log "docker compose not found. Please install docker compose plugin or docker-compose."
    exit 1
  fi
}

validate_runtime() {
  local runtime="$INSTALL_ROOT/config/runtime.yaml"
  python3 - <<'PY' "$runtime"
import sys, yaml, pathlib, socket
p = pathlib.Path(sys.argv[1])
cfg = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
ng = cfg.get('nginx', {})
http_port = ng.get('http_port')
https_enabled = ng.get('https_enabled', False)
https_port = ng.get('https_port')
backend_port = ng.get('backend_port')
server_name = ng.get('server_name', '_')
if not isinstance(http_port, int) or http_port <= 0:
    raise SystemExit('invalid nginx.http_port')
if not isinstance(backend_port, int) or backend_port <= 0:
    raise SystemExit('invalid nginx.backend_port')
if server_name == '':
    raise SystemExit('invalid nginx.server_name')
if https_enabled:
    if not isinstance(https_port, int) or https_port <= 0:
        raise SystemExit('invalid nginx.https_port')
    cert = pathlib.Path(ng.get('ssl_cert', ''))
    key = pathlib.Path(ng.get('ssl_key', ''))
    if not cert.exists():
        raise SystemExit(f'ssl cert not found: {cert}')
    if not key.exists():
        raise SystemExit(f'ssl key not found: {key}')
for port_name, port in [('http_port', http_port), ('backend_port', backend_port), ('https_port', https_port if https_enabled else None)]:
    if port is None:
        continue
    if not (1 <= int(port) <= 65535):
        raise SystemExit(f'invalid {port_name}: {port}')
print('runtime validation ok')
PY
}

check_port_conflicts() {
  local runtime="$INSTALL_ROOT/config/runtime.yaml"
  python3 - <<'PY' "$runtime"
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1], encoding='utf-8').read()) or {}
ng = cfg.get('nginx', {})
ports = []
ports.append(('http_port', ng.get('http_port')))
ports.append(('backend_port', ng.get('backend_port')))
if ng.get('https_enabled'):
    ports.append(('https_port', ng.get('https_port')))
seen = {}
for name, port in ports:
    if port in seen:
        raise SystemExit(f'port conflict: {name} conflicts with {seen[port]} on {port}')
    seen[port] = name
print('port conflict check ok')
PY
}

sync_project() {
  log "sync project to $INSTALL_ROOT"
  mkdir -p "$INSTALL_ROOT"
  cp -a "$BASE_DIR/." "$INSTALL_ROOT/"
  chmod +x "$INSTALL_ROOT/bin/xstrm" "$INSTALL_ROOT/bin/xstrm-admin" "$INSTALL_ROOT/scripts/"*.sh "$INSTALL_ROOT/scripts/strm_x.py" "$INSTALL_ROOT/scripts/render_runtime.py" "$INSTALL_ROOT/scripts/admin_api.py"
}

configure_runtime() {
  log "configure runtime interactively"
  python3 "$INSTALL_ROOT/scripts/configure_runtime.py"
}

render_runtime() {
  log "render runtime config"
  python3 "$INSTALL_ROOT/scripts/render_runtime.py"
}

apply_runtime() {
  log "apply runtime into live nginx/emby2alist config files"
  python3 "$INSTALL_ROOT/scripts/apply_runtime.py"
}

install_bin() {
  ln -sf "$INSTALL_ROOT/bin/xstrm" "$BIN_LINK"
  ln -sf "$INSTALL_ROOT/bin/xstrm-admin" "$ADMIN_LINK"
  log "installed command: $BIN_LINK"
  log "installed admin command: $ADMIN_LINK"
}

install_services() {
  if [ -f "$INSTALL_ROOT/services/xstrm.service" ]; then
    cp "$INSTALL_ROOT/services/xstrm.service" "$SERVICE_DIR/xstrm.service"
    sed -i 's#/opt/xstrm-suite#'$INSTALL_ROOT'#g' "$SERVICE_DIR/xstrm.service"
    log "installed service template: xstrm.service"
  fi
  if [ -f "$INSTALL_ROOT/services/xstrm-admin-api.service" ]; then
    cp "$INSTALL_ROOT/services/xstrm-admin-api.service" "$SERVICE_DIR/xstrm-admin-api.service"
    sed -i 's#/opt/xstrm-suite#'$INSTALL_ROOT'#g' "$SERVICE_DIR/xstrm-admin-api.service"
    log "installed service template: xstrm-admin-api.service"
  fi
}

show_next_steps() {
  cat <<EOF

[done] xstrm-suite bootstrap completed

Installed to:
  $INSTALL_ROOT

Command:
  xstrm

Next recommended steps:
  1. edit config: $INSTALL_ROOT/config/strm-sync.yaml
  2. review emby2alist config: $INSTALL_ROOT/emby2alist/emby2Alist/conf.d/config/constant-mount.js
  3. run: xstrm

EOF
}

main() {
  install_python
  check_docker
  sync_project
  configure_runtime
  validate_runtime
  check_port_conflicts
  render_runtime
  apply_runtime
  install_bin
  install_services
  if [ -x "$INSTALL_ROOT/scripts/nginx_ctl.sh" ]; then
    "$INSTALL_ROOT/scripts/nginx_ctl.sh" test
  fi
  show_next_steps
}

main "$@"
