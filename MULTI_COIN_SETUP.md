# Multi-Coin Trading Setup Guide

## What Changed?

Your bot now supports **trading multiple coins simultaneously**! 

### New Features:
✅ Dashboard UI to select which coins to trade  
✅ Independent bot process for each enabled pair  
✅ Per-pair leverage and quantity settings  
✅ Centralized bot manager handles all instances  
✅ Database-driven configuration  

---

## Deployment Steps

### 1. Update Database Schema
The database will auto-create the new `pair_config` table on next run, but you can also manually initialize:

```bash
cd /home/ubuntu/trading-bot
source venv/bin/activate
python -c "import sys; sys.path.insert(0, 'bot'); import db; db.init_db()"
```

### 2. Update Systemd Service
Copy the updated service file:

```bash
sudo cp bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload
```

### 3. Restart Services
```bash
# Restart the bot (now uses bot_manager.py)
sudo systemctl restart bot

# Check status
sudo systemctl status bot

# Restart dashboard server (to load new API endpoints)
sudo systemctl restart server
```

### 4. Configure Pairs via Dashboard
1. Open dashboard: `http://your-server-ip`
2. Scroll to **"Coin Manager"** section
3. Toggle coins you want to trade (BTC, ETH, SOL, etc.)
4. Set leverage and quantity for each pair
5. Click **"Apply Changes & Restart Bots"**

---

## How It Works

### Architecture:
```
bot_manager.py (main process)
    ├── main.py B-BTC_USDT  (child process)
    ├── main.py B-ETH_USDT  (child process)
    └── main.py B-SOL_USDT  (child process)
```

- **bot_manager.py**: Reads enabled pairs from database, spawns/manages individual bot processes
- **main.py**: Each instance trades one specific pair (passed as command-line argument)
- **Database**: Stores which pairs are enabled and their settings

### Process Flow:
1. Dashboard updates `pair_config` table
2. Bot manager checks database every 30 seconds
3. Starts new bots for enabled pairs
4. Stops bots for disabled pairs
5. Auto-restarts crashed bots

---

## Default Pairs Available

The dashboard shows popular USDT pairs:
- BTC/USDT
- ETH/USDT  
- SOL/USDT
- XRP/USDT
- BNB/USDT
- ADA/USDT
- DOGE/USDT
- MATIC/USDT
- DOT/USDT
- AVAX/USDT

---

## Monitoring

### Check running bots:
```bash
# See all bot processes
ps aux | grep main.py

# Check bot manager logs
tail -f /home/ubuntu/trading-bot/data/bot_manager.log

# Check individual bot logs
tail -f /home/ubuntu/trading-bot/data/bot.log
```

### Dashboard:
- **Trade History** now shows which pair each trade belongs to
- **All metrics** aggregate across all enabled pairs
- **Logs** show start/stop events for each pair

---

## Configuration Reference

### Database Table: `pair_config`
```sql
CREATE TABLE pair_config (
    pair       TEXT UNIQUE,      -- e.g., "B-BTC_USDT"
    enabled    INTEGER,          -- 0=off, 1=on
    leverage   INTEGER,          -- 1-20
    quantity   REAL             -- Order size in base currency
);
```

### API Endpoints:
- `GET /api/pairs/available` - List all tradable pairs from CoinDCX
- `GET /api/pairs/config` - Get current pair configurations
- `POST /api/pairs/config/update` - Update single pair config
- `POST /api/pairs/config/bulk` - Bulk update multiple pairs

---

## Troubleshooting

### Bots not starting?
```bash
# Check bot manager status
sudo systemctl status bot

# Check logs
tail -50 /home/ubuntu/trading-bot/data/bot_manager.log
```

### Pairs not showing in dashboard?
- Check CoinDCX API connection
- Visit `/api/pairs/available` to see raw response
- Check browser console for errors

### Changes not applying?
- Make sure to click "Apply Changes" button
- Restart bot service manually if auto-restart fails:
  ```bash
  sudo systemctl restart bot
  ```

---

## Safety Notes

⚠️ **Each enabled pair trades independently with its configured leverage/quantity**

⚠️ **Total capital usage = sum of all enabled pairs**  
Example: 3 pairs × 0.001 BTC × 5x leverage = significant exposure

⚠️ **Start with 1-2 pairs** to test before scaling up

⚠️ **Monitor overall position risk** across all pairs

---

## Reverting to Single-Pair Mode

If you want to go back to trading just one pair:

1. In dashboard, disable all pairs except one (e.g., BTC)
2. Or edit `bot.service` to use `bot/main.py` instead of `bot/bot_manager.py`
3. Restart: `sudo systemctl restart bot`

---

**That's it! Your bot is now multi-coin capable.** 🚀
