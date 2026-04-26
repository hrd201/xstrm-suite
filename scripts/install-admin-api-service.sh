#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="/opt/xstrm-suite"
SERVICE_FILE="/etc/systemd/system/xstrm-admin-api.service"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=XSTRM Admin API
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT
ExecStart=/usr/bin/python3 $INSTALL_ROOT/scripts/admin_api.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now xstrm-admin-api.service
systemctl --no-pager --full status xstrm-admin-api.service
