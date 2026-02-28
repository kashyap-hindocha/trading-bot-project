# Trading Bot — Functionality Review

**Purpose**: Crypto futures auto-trading on CoinDCX. This document describes what is **currently implemented** and what **must be improved or changed** for reliable automatic trading.

---

## 1. What Is Currently Implemented

### 1.1 Core flow (bot)

| Component | Implementation |
|-----------|----------------|
| **Process model** | `bot_manager.py` (one process) spawns one `main.py <PAIR>` per **enabled** pair; syncs every 30s with DB (start new, stop disabled, restart crashed). |
| **Data** | Each bot: seed 200×5m candles via REST → maintain in-memory buffer; subscribe to WebSocket `candlestick@{pair}@5m` and `ltp@futures@{pair}`. |
| **Candle handling** | On each candlestick: append/update buffer; **only on closed candle** run strategy, check paper TP/SL, then optionally execute. |
| **5m fallback** | If WebSocket doesn’t deliver closed candles, a thread runs at each 5m UTC boundary, fetches last-closed candle via REST, updates buffer and runs same strategy/paper logic. |
| **Strategy** | Single strategy in use: **Double EMA Pullback** (EMA50/200, crossover + pullback). Returns signal (LONG/SHORT/None), confidence (0–100, with “readiness” when no signal), TP/SL %. |
| **Execution rules** | Global cap: max 3 open trades total (any pairs). Per-pair cap from strategy config (`max_open_trades`, default 1). Optional re-entry cooldown. Confidence threshold from DB (e.g. 80%); only execute if signal and confidence ≥ threshold. |
| **Modes** | **PAPER**: Simulated entry/exit in DB; TP/SL checked on candle high/low; paper wallet updated. **REAL**: REST `place_order` (limit at current price) → poll for `position_id` → `place_tp_sl` → `insert_trade`. |
| **Position close (real)** | WebSocket `position_update` with status closed/liquidated → `db.close_trade(position_id, exit_price, pnl)`. |
| **Equity** | Background thread every 15 min: snapshot balance to `equity_snapshots` or `paper_equity_snapshots`. |

### 1.2 Exchange (CoinDCX)

| Feature | Implementation |
|--------|----------------|
| **REST** | Auth, retries, rate-limit backoff. Endpoints: candles (public), wallet, positions, create order, create_tp_sl, cancel, exit position, trade history. |
| **Candles** | Public API; returned newest-first, reversed to oldest-first for strategies. |
| **Order type** | **Limit** at current price (no market order). |
| **Sizing** | Per-pair: fixed quantity or INR amount (via INR/USDT rate) × leverage → notional → quantity. |
| **WebSocket** | Connect to `wss://stream.coindcx.com`, join channels; handlers for `candlestick`, `position_update`, `order_update`. |

### 1.3 Database (SQLite)

| Table / concept | Implementation |
|-----------------|----------------|
| **Path** | Hardcoded `DB_PATH = "/home/ubuntu/trading-bot/data/bot.db"` (no env override). |
| **Tables** | `trades`, `paper_trades`, `pair_config`, `pair_execution_status`, `trading_mode`, `paper_wallet`, `bot_config`, `bot_log`, equity snapshots. |
| **bot_config** | `active_strategy`, `confidence_threshold` (default 80%). |
| **pair_config** | `enabled`, leverage, quantity, inr_amount; columns for auto_enabled / readiness exist but no server batch auto-enable implemented. |

### 1.4 Server (Flask API)

| Area | Implementation |
|------|----------------|
| **APIs** | Mode, status, bot start/stop, strategies + threshold, pair config (CRUD, bulk), pair_signals (with server-computed confidence), current_confidence, paper execute/close, trades/positions (real and paper), equity, logs, candles, live positions (CoinDCX), bot logs (file tail). |
| **Strategy loading** | Tries project-relative `../bot` first, else `/home/ubuntu/trading-bot/bot`. |
| **Paper execute** | Runs strategy on server; only creates paper trade if strategy returns a **signal** (LONG/SHORT). |

### 1.5 Dashboard (frontend)

| Feature | Implementation |
|---------|----------------|
| **UI** | Balance, PnL, win rate, open positions, paper stats, mode toggle, strategy + confidence threshold, bot start/stop, pair cards (enabled pairs) with Last/Current %, Execute (paper), open trades (real/paper), charts, logs. |
| **Refresh** | fetchAll every 5s; pair_signals every 5s (with server-computed current %); current_confidence fallback every 30s. |

---

## 2. What Must Be Improved or Changed

### 2.1 Critical for automatic crypto futures trading

| # | Issue | Current state | Recommended change |
|---|--------|----------------|-------------------|
| 1 | **Hardcoded paths** | `.env`, `DB_PATH`, log paths, data dir all point to `/home/ubuntu/trading-bot/...`. | Use env (e.g. `BOT_DATA_DIR`, `BOT_DB_PATH`) with a default; same for server `.env` and log path. Allows local/dev and different servers. |
| 2 | **Order type** | Entry is **limit at current price**. In fast moves the order may never fill. | Add **market order** option (or “limit with short TTL then market”) for execution-critical entries, and make it configurable per strategy or global. |
| 3 | **Position ID after order** | If exchange doesn’t return `position_id` in create response, bot polls positions and may match by pair only → wrong position if multiple. | Prefer position_id from order response; if polling, match by `order_id` when API provides it; add timeout and clear failure path (e.g. cancel or alert) instead of attaching TP/SL to wrong position. |
| 4 | **WebSocket event naming** | Bot subscribes to `candlestick@{pair}@5m` but registers handler for event name `"candlestick"`. CoinDCX might push under the channel name or a different event. | Verify against CoinDCX WebSocket docs; if events are channel-named, register a handler for the actual event (e.g. `candlestick@B-BTC_USDT@5m`) or normalize in a single handler. |
| 5 | **Real position close** | Close is driven only by WebSocket `position_update`. If the event is never received (e.g. connection drop, API change), DB will show open forever. | Persist position_id and sync with REST periodically (e.g. `/positions`); if position is closed on exchange but still open in DB, call `db.close_trade` with data from API. |
| 6 | **Single strategy** | Only **Double EMA Pullback** is present. Docs mention enhanced_v2 / readiness; codebase has only one strategy. | Either add more strategies (e.g. trend + filters) or clearly document that the bot is “single-strategy” and readiness in UI is from that strategy’s confidence/readiness. |

### 2.2 Important for production

| # | Issue | Current state | Recommended change |
|---|--------|----------------|-------------------|
| 7 | **Candles source** | Candles from **public** API; comment in code notes it may differ from futures UI. | Confirm whether CoinDCX has a **futures-specific** candles endpoint; if yes, use it so signals match the product you trade. |
| 8 | **No circuit breaker** | Repeated API/WS failures can lead to many retries and unclear state. | Add simple circuit breaker (e.g. after N failures in a window, pause execution and log/alert; resume after cooldown or manual reset). |
| 9 | **Paper wallet init** | Paper balance is only set when user switches to PAPER mode (copy from real balance). If real balance fetch fails, paper can stay null/zero. | On first PAPER use, if real balance unavailable, set a default (e.g. from config) and log clearly so paper mode is always usable. |
| 10 | **Bot manager sync interval** | 30s means new pairs get a bot up to 30s after enable; disabled pairs can keep running up to 30s. | Consider shorter interval (e.g. 10s) or event-driven update when pair config changes (e.g. server notifies or writes a “config version” the manager polls). |
| 11 | **Trailing stop** | Strategy can return `trailing_stop`; it’s stored in DB and logged but **not** applied on exchange or in paper (paper only uses fixed TP/SL). | Either implement trailing stop (exchange if supported, or paper logic that updates SL on each candle) or remove from UI/DB to avoid confusion. |

### 2.3 Consistency and ops

| # | Issue | Current state | Recommended change |
|---|--------|----------------|-------------------|
| 12 | **Docs vs code** | PROJECT_ANALYSIS.md describes batch checker, readiness, auto_enabled, enhanced_v2. None of that exists in current server/bot code. | Update PROJECT_ANALYSIS and ARCHITECTURE to match current code (single strategy, no batch auto-enable, server-computed confidence in pair_signals). |
| 13 | **systemd / deploy** | Bot start/stop in dashboard call `systemctl start/stop bot`. Assumes same machine and sudo. | Document that dashboard bot control is for “same-server” deployment; for remote or no-sudo, provide alternative (e.g. API that sets a “desired state” flag and a separate controller that starts/stops processes). |
| 14 | **Errors and observability** | Errors are logged and some written to `bot_log`; no metrics or alerts. | Add simple health/readiness endpoint (e.g. “last candle time”, “last strategy run”) and optional alerting (e.g. Telegram/Discord on repeated execution failure or WS disconnect). |
| 15 | **Confidence threshold** | Stored in DB and applied in bot and server. Strategy also has its own `confidence_threshold` in CONFIG; bot uses DB only. | Ensure single source of truth (DB) and document; remove or clearly subordinate strategy’s CONFIG threshold so it’s not confusing. |

### 2.4 Optional enhancements (for robustness)

| # | Item | Suggestion |
|---|------|------------|
| 16 | **Quantity rounding** | Exchange likely has lot-size/step rules. | Round quantity to exchange tick/lot size before place_order to avoid rejections. |
| 17 | **Partial fills** | Not handled; order is treated as one fill. | If API supports fill events, consider updating position size and TP/SL when partial fills occur. |
| 18 | **Rate limits** | REST has retries; no global rate limiter across pairs. | With many pairs, consider a shared throttle for order/position APIs to stay under exchange limits. |
| 19 | **Graceful shutdown** | Bot manager catches SIGTERM/SIGINT and stops children; each main.py may be killed mid-order. | In main.py, on signal, finish current candle evaluation and avoid starting new orders; then exit. |

---

## 3. Summary Table

| Category | Implemented | Must improve/change |
|----------|-------------|----------------------|
| **Auto execution** | Yes: closed candle → strategy → threshold → PAPER/REAL order + TP/SL | Order type (market option), position_id handling, WS event name |
| **Multi-pair** | Yes: one process per enabled pair, max 3 open total | — |
| **Paper mode** | Yes: full simulate with TP/SL on candle | Paper wallet init, optional trailing stop |
| **Real mode** | Yes: limit order, TP/SL, position close via WS | Position sync with REST, market order option |
| **Config & UI** | Yes: mode, strategy, threshold, pairs, dashboard | Docs, env-based paths, health/alerting |
| **Data & reliability** | Candles + 5m fallback, retries | Candles source (futures?), circuit breaker, WS event name |

---

## 4. Suggested Priority Order

1. **Paths and env** — Make DB, .env, and log paths configurable (env vars with defaults).
2. **WebSocket** — Confirm CoinDCX event name for candlestick and fix handler if needed.
3. **Position lifecycle** — Periodic REST sync of open positions and DB state; ensure position_id is correct when placing TP/SL.
4. **Order execution** — Add market order (or hybrid) and document when to use it.
5. **Docs** — Align PROJECT_ANALYSIS and ARCHITECTURE with current code.
6. **Trailing stop** — Either implement (exchange/paper) or remove from scope.
7. **Ops** — Health endpoint and optional alerts for failures/disconnects.

This keeps the current “automatically trade when strategy and threshold say so” behaviour while making it deployable, observable, and aligned with the exchange’s behaviour.
