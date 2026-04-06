#!/usr/bin/env bash
# Serve the dashboard at http://YOUR_IP/ (port 80) by proxying to the app on 127.0.0.1:8000.
# Run once on the server (after trading-bot systemd is working). Requires sudo.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_SRC="${SCRIPT_DIR}/nginx-algotrader.conf"
CONF_DST="/etc/nginx/sites-available/algotrader"

if [[ ! -f "$CONF_SRC" ]]; then
  echo "Missing $CONF_SRC" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y nginx

sudo cp "$CONF_SRC" "$CONF_DST"
sudo ln -sf "$CONF_DST" /etc/nginx/sites-enabled/algotrader

# Avoid conflicting default site also binding :80
if [[ -L /etc/nginx/sites-enabled/default ]]; then
  sudo rm -f /etc/nginx/sites-enabled/default
fi

sudo nginx -t
sudo systemctl enable nginx
sudo systemctl reload nginx

echo "Done. Open http://$(hostname -I 2>/dev/null | awk '{print $1}')/ (no port)."
echo "Oracle: allow ingress TCP 80 on the VCN security list / NSG (you can keep 8000 closed publicly)."
