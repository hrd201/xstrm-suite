#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="/opt/xstrm-suite"
NGINX_CONF="$INSTALL_ROOT/nginx/nginx.conf"
SITE_HTTP="$INSTALL_ROOT/nginx/sites-enabled/xstrm-http.conf"
SITE_HTTPS="$INSTALL_ROOT/nginx/sites-enabled/xstrm-https.conf"

cmd="${1:-status}"

case "$cmd" in
  test)
    nginx -t -c "$NGINX_CONF"
    ;;
  reload)
    nginx -t -c "$NGINX_CONF"
    nginx -s reload
    ;;
  status)
    ps -ef | grep '[n]ginx' || true
    ;;
  paths)
    echo "conf: $NGINX_CONF"
    echo "http site: $SITE_HTTP"
    echo "https site: $SITE_HTTPS"
    ;;
  *)
    echo "usage: $0 {test|reload|status|paths}"
    exit 1
    ;;
esac
