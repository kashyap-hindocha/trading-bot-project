# CoinDCX Algo Trader

Single-user trading stack: market OHLCV → indicators / rules → paper or live CoinDCX margin orders, with a FastAPI dashboard.

**Price feed:** CoinDCX’s public REST candles for many pairs are **months stale** (frozen JSON), which produced wrong LTP (~120k vs real ~69k USD). Default **`OHLC_SOURCE=auto`** detects that and switches **OHLC + LTP** to **Binance spot** for the **active pair** (chosen in the dashboard; stored in SQLite) so charts and fills match **TradingView** for that symbol. **Live** orders still go through **CoinDCX**. Set `OHLC_SOURCE=coindcx` only if you trust that feed for your pair.

## Quick start (local)

1. Python 3.10+ recommended.
2. Copy environment template and edit secrets:

   ```bash
   cp .env.example .env
   ```

3. **Use a virtual environment** (required on Ubuntu/Debian — avoids `externally-managed-environment` / PEP 668):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   If `python3 -m venv .venv` fails with “ensurepip is not available”, install the venv package for your Python version, e.g.:

   ```bash
   sudo apt install python3.12-venv
   ```

   If `source .venv/bin/activate` says **No such file or directory**, the venv was created without `activate` / `pip` (incomplete). Remove it and recreate **after** installing `python3.xx-venv`:

   ```bash
   rm -rf .venv
   sudo apt install python3.12-venv
   python3 -m venv .venv
   ls .venv/bin/activate   # should exist
   source .venv/bin/activate
   ```

4. Run the app (keep `PYTHONPATH` set to the project root):

   ```bash
   export PYTHONPATH=.
   python start.py
   ```

5. Open `http://127.0.0.1:8000` (or your `WEB_PORT`).

   Next time, activate the venv first: `source .venv/bin/activate`.

## Server (Oracle / VPS, no Docker)

Docker is **not** required. On a small VM (e.g. Oracle Free Tier), use a **venv** and **systemd** so the app restarts on boot and does not need an open SSH session.

**One-time on the server** (from the project directory):

```bash
chmod +x scripts/deploy_ubuntu.sh
./scripts/deploy_ubuntu.sh
```

That creates `.venv`, installs dependencies, and installs a **`trading-bot`** systemd unit. Edit `.env` first (or after) for secrets.

**Useful commands:**

```bash
sudo systemctl status trading-bot
journalctl -u trading-bot -f
sudo systemctl restart trading-bot
```

Manual run (dev): `export PYTHONPATH=. && source .venv/bin/activate && python start.py`

A **systemd unit template** is in `scripts/trading-bot.service.example` if you prefer to install the service by hand.

## API (spec)

- `GET /health` — liveness.
- `GET /api/status` — mode, balance (paper), positions, recent signals and trades.
- `GET /api/trades?paper=true|false` — trade list.
- `POST /api/mode` — `{"mode":"paper"|"live"}`.
- `POST /api/indicator/upload` — `{"name":"...","pine_code":"..."}` — **requires** Pine→Python compile (`pine2py`); activates `user:active` only on success (422 if compile/validation fails; draft still saved).
- `POST /api/order/manual` — manual order body per spec (`symbol`, `side`, `quantity`, `leverage`, `tp_price`, `sl_price`, `market`).
- `POST /api/order/close` — paper only: `{"trade_id":"..."}` to market-close an open paper position at current LTP.
- `POST /api/risk/update` — persists `risk:*` keys in SQLite `config` table (optional UI).

## Pine compile (required)

Trading signals come **only** from your Pine script. `pip install -r requirements.txt` installs **`pine2py`** (git) for Pine→Python compilation. The dashboard **Save Pine & compile** must succeed (HTTP 200) before `user_indicators/active.py` is updated and trading uses it.

If the translator does not emit `compute()`, the server appends a small **stub** `compute(closes, **params)` you should edit so the last-bar logic matches TradingView. If compile fails, fix the Pine or dependencies; your draft is still stored in SQLite.

## Ubuntu / Oracle VPS

See `scripts/deploy_ubuntu.sh` (venv + systemd, no Docker).

## Tests

```bash
pip install -r requirements.txt
pytest
```

## Notes

- Timestamps are stored and logged in UTC.
- CoinDCX public stream uses **Socket.IO** (`python-socketio` client) at `https://stream.coindcx.com`, channels such as `B-BTC_USDT_1m`.
- Live trading uses authenticated REST to `https://api.coindcx.com` (margin endpoints). The tradable **pair** (`market`, `ecode`, `pair` channel) comes from the dashboard and [CoinDCX market metadata](https://docs.coindcx.com), not from `.env`.
