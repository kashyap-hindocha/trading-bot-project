#!/bin/bash
# Quick deployment script for multi-coin trading bot

set -e

echo "🚀 Deploying Multi-Coin Trading Bot..."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BOT_HOME="${BOT_HOME:-$(cd "$(dirname "$0")" && pwd)}"
cd "$BOT_HOME"

# 1. Initialize database
echo -e "${GREEN}✓${NC} Initializing database..."
source venv/bin/activate
python -c "import sys; sys.path.insert(0, 'bot'); import db; db.init_db()"

# 2. Update systemd service
echo -e "${GREEN}✓${NC} Updating systemd service..."
sudo cp bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload

# 3. Restart services
echo -e "${GREEN}✓${NC} Restarting services..."
sudo systemctl restart server
sleep 2
sudo systemctl restart bot
sleep 2

# 4. Check status
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}Bot Manager Status:${NC}"
sudo systemctl status bot --no-pager -l | head -15
echo ""
echo -e "${GREEN}Dashboard Server Status:${NC}"
sudo systemctl status server --no-pager -l | head -15
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "📊 Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_SERVER_IP')"
echo "📝 Manager Logs: tail -f $BOT_HOME/data/bot_manager.log"
echo "📝 Bot Logs: tail -f $BOT_HOME/data/bot.log"
echo ""
echo "Next steps:"
echo "  1. Open the dashboard"
echo "  2. Go to 'Coin Manager' section"
echo "  3. Toggle coins you want to trade"
echo "  4. Set leverage & quantity for each"
echo "  5. Click 'Apply Changes'"
echo ""
