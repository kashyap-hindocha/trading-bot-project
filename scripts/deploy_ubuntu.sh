#!/usr/bin/env bash
set -euo pipefail
# Oracle / Ubuntu VPS: Python venv + systemd (no Docker). Run once on a fresh server.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

SERVICE_NAME="${SERVICE_NAME:-trading-bot}"
RUN_USER="${SUDO_USER:-$USER}"
if [[ "$RUN_USER" == "root" ]]; then
  RUN_USER="$(id -un 1000 2>/dev/null || echo ubuntu)"
fi

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit secrets before live trading."
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ ! -f "$SERVICE_FILE" ]; then
  echo "Creating systemd unit $SERVICE_FILE"
  sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=AlgoTrader CoinDCX dashboard (uvicorn)
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_ROOT}
EnvironmentFile=${PROJECT_ROOT}/.env
Environment=PYTHONPATH=${PROJECT_ROOT}
ExecStart=${PROJECT_ROOT}/.venv/bin/python ${PROJECT_ROOT}/start.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
fi

sudo systemctl restart "$SERVICE_NAME"
echo "Service: $SERVICE_NAME"
echo "Status: sudo systemctl status $SERVICE_NAME"
echo "Logs:   journalctl -u $SERVICE_NAME -f"
IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
echo "Dashboard (if firewall allows): http://${IP}:8000"
