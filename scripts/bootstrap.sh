#!/usr/bin/env bash
# Backward-compatible entry point; keep one dependency/user/service install path.
set -euo pipefail
exec bash "$(dirname "$0")/install.sh" "$@"
