#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$BASE_DIR/docker-compose.yml"
cmd="${1:-status}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

if need_cmd docker && docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f "$COMPOSE_FILE")
elif need_cmd docker-compose; then
  DC=(docker-compose -f "$COMPOSE_FILE")
else
  echo "docker compose not found"
  exit 1
fi

case "$cmd" in
  up)
    "${DC[@]}" up -d
    ;;
  down)
    "${DC[@]}" down
    ;;
  restart)
    "${DC[@]}" restart
    ;;
  logs)
    "${DC[@]}" logs --tail=100 -f
    ;;
  ps|status)
    "${DC[@]}" ps
    ;;
  pull)
    "${DC[@]}" pull
    ;;
  *)
    echo "usage: $0 {up|down|restart|logs|ps|status|pull}"
    exit 1
    ;;
esac
