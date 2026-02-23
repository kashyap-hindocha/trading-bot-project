# Multi-Coin Trading Setup Guide

## What Changed?

Your bot now supports **trading multiple coins simultaneously** with **automated confidence-based pair management**! 

### New Features:
✅ **Automated confidence-based pair enabling** — Pairs with >75% strategy confidence are auto-enabled  
✅ **Batch processing** — Evaluates 5 pairs at a time to avoid API exhaustion  
✅ **2-minute cycle** — Full confidence check runs every 2 minutes  
✅ **Auto-disable on drop** — Pairs below 75% confidence are automatically disabled  
✅ Independent bot process for each enabled pair  
✅ Per-pair leverage and quantity settings (defaults for auto-enabled pairs)  
✅ Centralized bot manager handles all instances  
✅ Database-driven configuration  

### Removed:
❌ **Pair Manager** — Manual pair selection has been removed. Pairs are now enabled/disabled automatically based on strategy confidence.

---

## Automated Confidence Check Cycle

The system runs a background process that:

1. **Every 2 minutes** — Evaluates all configured trading pairs in batches of 5
2. Iterates through all pairs (e.g. 1–5, 6–10, …); any pair with confidence > 75% is auto-enabled, any auto-enabled pair below 75% is disabled
3. **Dashboard** — Shows current batch (pair names + confidence %), countdown to next cycle, and last confidence history (15 per page, paginated)

### Batch Processing
- Exactly **5 pairs per batch** to prevent API exhaustion and request timeouts
- UI displays the 5 pairs currently being evaluated with their confidence level
- Countdown timer shows time until the next 2-minute cycle

### Auto-Enable / Auto-Disable
- **Enable**: Confidence > 75% → pair is enabled for trading (no manual action)
- **Disable**: Confidence drops below 75% at the start of a cycle → pair is disabled
- Default leverage (5x), quantity (0.001), and INR amount (300) for newly auto-enabled pairs

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

### 4. Seed Pair Config (First Run)
On first run, if `pair_config` is empty, the batch checker seeds it from CoinDCX's active instruments (USDT pairs). No manual configuration is required for the confidence check to start.

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
1. **Batch confidence checker** (runs in server process) evaluates pairs every 10 minutes in batches of 5
2. Pairs with confidence > 75% are auto-enabled; pairs below 75% are auto-disabled
3. Bot manager checks database every 30 seconds
4. Starts new bots for enabled pairs
5. Stops bots for disabled pairs
6. Auto-restarts crashed bots

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
- **Confidence Check (Background)** — Shows batch status, which pairs are being evaluated, countdown to next cycle, and auto-enabled pairs with confidence bars
- **Trading Pairs** — Shows enabled pairs sorted by signal strength (auto-enabled pairs)
- **Trade History** — Shows which pair each trade belongs to
- **All metrics** aggregate across all enabled pairs
- **Logs** show start/stop events and auto-enable/disable actions

---

## Configuration Reference

### Database Table: `pair_config`
```sql
CREATE TABLE pair_config (
    pair         TEXT UNIQUE,      -- e.g., "B-BTC_USDT"
    enabled      INTEGER,          -- 0=off, 1=on
    auto_enabled INTEGER DEFAULT 0, -- 1=was auto-enabled by batch checker
    leverage     INTEGER,          -- 1-20
    quantity     REAL,             -- Order size in base currency
    inr_amount   REAL              -- INR amount per trade
);
```

### API Endpoints:
- `GET /api/pairs/available` - List all tradable pairs from CoinDCX
- `GET /api/pairs/config` - Get current pair configurations
- `POST /api/pairs/config/update` - Update single pair config
- `POST /api/pairs/config/bulk` - Bulk update multiple pairs
- `GET /api/batch/status` - Batch checker status (current batch, countdown, auto-enabled pairs)
- `GET /api/batch/auto-enabled` - Auto-enabled pairs with confidence/readiness for review panel

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

### Pairs not auto-enabling?
- Ensure strategy conditions are met (confidence must exceed 75%)
- Check server logs for batch checker errors
- Visit `/api/batch/status` to see current batch state and countdown

### Changes not applying?
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

1. Use `POST /api/pairs/config/update` to disable pairs you don't want (or wait for auto-disable when confidence drops)
2. Or edit `bot.service` to use `bot/main.py` instead of `bot/bot_manager.py`
3. Restart: `sudo systemctl restart bot`

---

**That's it! Your bot is now multi-coin capable.** 🚀
