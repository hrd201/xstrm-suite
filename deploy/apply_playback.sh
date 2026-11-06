#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f deploy/compose.test.yaml)
render() { "${compose[@]}" exec -T admin python deploy/render_mediawarp.py "$@"; }
backend=${1:-$(render backend)}
case "$backend" in mediawarp|emby2alist) ;; *) echo 'Unsupported playback backend' >&2; exit 1 ;; esac
umask 077
mkdir -p deploy/test-data
lock=deploy/test-data/playback-apply.lock
mkdir "$lock" || { echo 'Another playback apply is running' >&2; exit 1; }
snapshot=''
changed=0
mediawarp_changed=0
mediawarp_running=''
cleanup() {
  result=$?
  trap - EXIT
  if [[ "$result" -ne 0 ]]; then
    if [[ "$mediawarp_changed" -eq 1 ]]; then
      if [[ -f "$snapshot/mediawarp.yaml" ]]; then
        cp "$snapshot/mediawarp.yaml" deploy/test-mediawarp/config/config.yaml
      else
        rm -f deploy/test-mediawarp/config/config.yaml
      fi
      if [[ -n "$mediawarp_running" ]]; then
        "${compose[@]}" up -d --no-deps --force-recreate mediawarp && render ready || true
      else
        "${compose[@]}" stop mediawarp || true
      fi
      if [[ -f "$snapshot/mediawarp-proxy.conf" ]]; then
        cp "$snapshot/mediawarp-proxy.conf" deploy/test-nginx/conf.d/includes/mediawarp-proxy.conf
      fi
    fi
    if [[ "$changed" -eq 1 ]]; then
      cp "$snapshot/emby.conf" "$front"
      cp "$snapshot/constant.js" deploy/test-nginx/conf.d/constant.js
      cp "$snapshot/constant-mount.js" deploy/test-nginx/conf.d/config/constant-mount.js
      "${compose[@]}" exec -T gateway nginx -t && "${compose[@]}" exec -T gateway nginx -s reload || true
      echo 'Apply failed; previous playback files restored.' >&2
    fi
  fi
  rmdir "$lock"
  exit "$result"
}
trap cleanup EXIT
snapshot=$(mktemp -d deploy/test-data/playback-rollback.XXXXXXXX)
front=deploy/test-nginx/conf.d/emby.conf
legacy=deploy/test-data/emby2alist-gateway.conf
cp "$front" "$snapshot/emby.conf"
cp deploy/test-nginx/conf.d/constant.js "$snapshot/constant.js"
cp deploy/test-nginx/conf.d/config/constant-mount.js "$snapshot/constant-mount.js"
revision=$(render revision)
if [[ "$backend" == mediawarp ]]; then
  if grep -q 'js_import emby2Pan' "$front"; then cp "$front" "$legacy"; fi
  mkdir -p deploy/test-mediawarp/config
  if [[ -f deploy/test-mediawarp/config/config.yaml ]]; then cp deploy/test-mediawarp/config/config.yaml "$snapshot/mediawarp.yaml"; fi
  if [[ -f deploy/test-nginx/conf.d/includes/mediawarp-proxy.conf ]]; then cp deploy/test-nginx/conf.d/includes/mediawarp-proxy.conf "$snapshot/mediawarp-proxy.conf"; fi
  mediawarp_running=$("${compose[@]}" ps -q --status running mediawarp)
  render config > deploy/test-mediawarp/config/config.yaml.pending
  mediawarp_changed=1
  mv deploy/test-mediawarp/config/config.yaml.pending deploy/test-mediawarp/config/config.yaml
  render gateway > "$snapshot/mediawarp-gateway.conf"
  render proxy > "$snapshot/mediawarp-proxy.conf"
  cp "$snapshot/mediawarp-proxy.conf" deploy/test-nginx/conf.d/includes/mediawarp-proxy.conf
  "${compose[@]}" up -d --no-deps --force-recreate mediawarp
  render ready
  changed=1
  cp "$snapshot/mediawarp-gateway.conf" "$front"
else
  if [[ -f "$legacy" ]]; then
    changed=1
    cp "$legacy" "$front"
  elif ! grep -q 'js_import emby2Pan' "$front"; then
    echo 'No saved emby2Alist gateway configuration' >&2
    exit 1
  fi
  changed=1
  "${compose[@]}" exec -T admin python deploy/apply_playback.py
fi
"${compose[@]}" exec -T gateway nginx -t
"${compose[@]}" exec -T gateway nginx -s reload
render record --backend "$backend" --revision "$revision"
echo "Playback backend applied: $backend. Rollback files: $snapshot"
