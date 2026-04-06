#!/usr/bin/env bash
# Serve the dashboard at http://YOUR_IP/ (port 80) by proxying to the app on 127.0.0.1:8000.
# Run once on the server (after trading-bot systemd is working). Requires sudo.
#
# "rewrite or internal redirection cycle ... /index.html" means another nginx file is using
# SPA-style try_files. This script disables common conflicting defaults.

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

# Remove Ubuntu default site(s) — often static root + try_files (or SPA) on :80
sudo rm -f /etc/nginx/sites-enabled/default
sudo rm -f /etc/nginx/sites-enabled/default.conf

# Some images ship a default in conf.d that also binds :80 and uses try_files → /index.html cycles
if compgen -G "/etc/nginx/conf.d/*.conf" >/dev/null; then
  for c in /etc/nginx/conf.d/*.conf; do
    [[ -f "$c" ]] || continue
    if grep -qE 'listen\s+(\[::\]:)?80\b' "$c" 2>/dev/null && grep -q 'try_files' "$c" 2>/dev/null; then
      echo "Disabling conflicting $c (listen 80 + try_files)"
      sudo mv "$c" "${c}.disabled-by-algotrader"
    fi
  done
fi

sudo nginx -t
sudo systemctl enable nginx
sudo systemctl reload nginx

echo "Done. Open http://$(hostname -I 2>/dev/null | awk '{print $1}')/ (no port)."
echo "Oracle: allow ingress TCP 80 on the VCN security list / NSG."
echo "If problems remain: sudo nginx -T 2>&1 | grep -nE 'try_files|index\\.html'"
