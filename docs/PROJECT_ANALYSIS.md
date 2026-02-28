# Trading Bot — Project Analysis & Code-Flow Reference

**Purpose**: Single reference for code-flow, workflow, and documentation sync. Use this for fixing issues and enhancements. Keep in sync with `MULTI_COIN_SETUP.md` and `ARCHITECTURE.md`.

---

## 1. Project Purpose & Modes

| Aspect | Description |
|--------|-------------|
| **What it does** | Automates crypto futures trading on **CoinDCX**. When strategy conditions are met at sufficient confidence, it executes trades and sets **Take Profit (TP)** and **Stop Loss (SL)**. |
| **Real mode** | Live trades via CoinDCX REST API; TP/SL placed on exchange; positions closed via WebSocket `position_update`. |
| **Paper mode** | Simulated trades in DB only; TP/SL checked on each closed candle (high/low vs TP/SL); paper wallet updated on close. |

**High-level flow** (from ARCHITECTURE):

```
Seed candles → WebSocket candlesticks → Strategy evaluate → (if signal + auto_execute)
  → PAPER: insert paper trade, simulate TP/SL on candle
  → REAL:  place_order + place_tp_sl + insert trade
```

---

## 2. Architecture (aligned with MULTI_COIN_SETUP & ARCHITECTURE)

### Process layout

```
bot_manager.py (main process, systemd service "bot")
    ├── main.py B-BTC_USDT   (child)
    ├── main.py B-ETH_USDT   (child)
    └── main.py B-SOL_USDT   (child)
```

- **bot_manager.py**: Reads `pair_config` (enabled=1), spawns one `main.py <PAIR>` per enabled pair every 30s; stops disabled pairs; restarts crashed bots.
- **main.py**: Single-pair bot: seed candles → WebSocket → on closed candle → strategy evaluate → place order (REAL) or paper trade (PAPER) + TP/SL.
- **server/app.py**: Flask API + **batch confidence checker** (daemon thread). Batch checker runs every **10 minutes**: Phase 1 re-evaluates auto-enabled pairs (disable if below threshold), Phase 2 evaluates disabled pairs in batches of 5 (enable if above threshold). Uses **readiness** (see §6).

### Important: Readiness vs Confidence

| Term | Where | Meaning |
|------|--------|---------|
| **Readiness** | Server `_compute_readiness()`, batch checker, `/api/signal/readiness`, `/api/batch/auto-enabled` | **Proximity** to trade conditions (EMA gap + RSI alignment, 0–100%). Used for **auto-enable/disable** pairs. |
| **Confidence** | Strategy `evaluate()` (e.g. enhanced_v2), stored in `trades` / `paper_trades` | Full strategy score (EMA + MACD + RSI + volume + trend, 0–100%). Used for **actual trade execution** and `auto_execute`. |

MULTI_COIN_SETUP and log messages say "confidence > 75%" for auto-enable; in code the batch checker uses **readiness** (same 75% threshold). The two metrics are different; both use 75% as threshold.

---

## 3. Code Flow (main paths)

### 3.1 Bot manager loop (`bot/bot_manager.py`)

1. `init_db()`, register SIGTERM/SIGINT.
2. Every 30s: `sync_bots_with_config()`:
   - `get_enabled_pairs()` from DB.
   - Stop bots for pairs no longer enabled.
   - Start bots for newly enabled pairs.
   - Restart any crashed bot (process exited) for still-enabled pairs.

### 3.2 Single-pair bot (`bot/main.py`)

1. **Init**: Parse `PAIR` from argv (default `B-BTC_USDT`). Load env, REST, Socket, strategy_manager (active: `enhanced_v2`).
2. **Seed**: `_seed_candles()` → REST `get_candles(PAIR, 5m, 200)` → fill `candle_buffer`.
3. **WebSocket**: `socket.connect(PAIR, INTERVAL)`, register `on_candlestick`, `on_position_update`, `on_order_update`.
4. **On candlestick** (`_update_candle`):
   - Append/update candle in `candle_buffer` (cap 200).
   - If candle **is_closed**:
     - `_check_paper_positions(candle)` (PAPER only): for open paper trades on this PAIR, check if candle high/low hit TP or SL; if so, close trade and update paper wallet.
     - `_run_strategy(candle["close"])`.
5. **Strategy run** (`_run_strategy`):
   - Enforce per-pair `max_open_trades` (from active strategy config).
   - `strategy_manager.evaluate(candle_buffer, return_confidence=True)` → `{signal, confidence, auto_execute, atr, position_size, trailing_stop}`.
   - If no signal or `not auto_execute`, return.
   - **PAPER**: `_run_paper_trade(...)` → deduct fee, `insert_paper_trade`, TP/SL from strategy.
   - **REAL**: `_get_pair_config()` + strategy config → `_resolve_trade_sizing()` (INR or fixed qty) → `rest.place_order()` → get `position_id` (from order or poll positions) → `active_strategy.calculate_tp_sl()` → `rest.place_tp_sl()` → `db.insert_trade()`.
6. **Position close (REAL)**: WebSocket `position_update` with status `closed`/`liquidated` → `on_position_update()` → `db.close_trade(position_id, exit_price, pnl)`.
7. **Equity snapshot**: Background thread every 15 min → `snapshot_equity(balance)` or `snapshot_paper_equity(balance)`.

### 3.3 Strategy (e.g. `bot/strategies/enhanced_v2.py`)

- **evaluate(candles, return_confidence=True)**:
  - Compute indicators (EMA, RSI, ATR, MACD, volume).
  - Detect EMA crossover + MACD alignment + volume check.
  - If LONG/SHORT: `calculate_confidence()`, `calculate_position_size()`, `calculate_trailing_stop()`, set `auto_execute = confidence >= confidence_threshold` (75%).
  - Return `{signal, confidence, auto_execute, atr, position_size, trailing_stop}`.
- **calculate_tp_sl(entry_price, position_type, atr)**: Uses `tp_pct` / `sl_pct` (e.g. 1.5% / 0.8%) to return (tp_price, sl_price).

### 3.4 Server batch checker (`server/app.py`)

- **Thread** `_batch_checker_loop`: while True → `_run_batch_cycle()` then `time.sleep(600)`.
- **Cycle**:
  - Seed `pair_config` from CoinDCX if empty.
  - Phase 1: `get_auto_enabled_pairs()` → in batches of 5, `_batch_compute_readiness(batch)` → if `readiness < 75%`, `update_pair_auto_status(pair, 0, 0)`.
  - Phase 2: disabled pairs in batches of 5, same readiness → if `readiness > 75%`, `update_pair_auto_status(pair, 1, 1)`.
- **Readiness**: `_compute_readiness(closes)` uses EMA gap + RSI vs overbought/oversold to produce a 0–100% “proximity” score (not full strategy confidence).

---

## 4. Database (bot/db.py)

- **Path**: `DB_PATH = "/home/ubuntu/trading-bot/data/bot.db"` (override in code if your path differs).
- **Key tables**:
  - `trades` / `paper_trades`: open/closed trades (pair, side, entry/exit, tp/sl, confidence, atr, position_size, trailing_stop, etc.).
  - `pair_config`: pair, enabled, auto_enabled, leverage, quantity, inr_amount.
  - `trading_mode`: singleton mode = REAL | PAPER.
  - `paper_wallet`: singleton balance for paper mode.
  - `bot_config`: pair_mode (SINGLE/MULTI), selected_pair.
  - `equity_snapshots` / `paper_equity_snapshots`, `bot_log`.

---

## 5. Key Files Quick Reference

| File | Role |
|------|------|
| `bot/bot_manager.py` | Spawns/stops/restarts `main.py <PAIR>` per enabled pair; 30s sync. |
| `bot/main.py` | Per-pair bot: WS candles → strategy → order/paper + TP/SL. |
| `bot/strategy_manager.py` | Loads strategies from `strategies/`, exposes evaluate/calculate_tp_sl. |
| `bot/strategy_base.py` | Abstract base TradingStrategy. |
| `bot/strategies/enhanced_v2.py` | EMA+MACD+RSI+ATR+volume; confidence & auto_execute. |
| `bot/strategy.py` | Standalone module for `/api/pair_signals` and `calculate_signal_strength` (mirrors enhanced_v2 logic). |
| `bot/coindcx.py` | CoinDCXREST, CoinDCXSocket (REST + WebSocket). |
| `bot/db.py` | SQLite: init_db, trades, paper_trades, pair_config, mode, etc. |
| `server/app.py` | Flask API + batch checker (readiness-based auto-enable/disable). |
| `dashboard/js/init.js` | Boot: loadPairs, fetchMode, loadStrategies, loadPairMode, loadPairSignals, refreshBatchUI, fetchAll, intervals. |
| `dashboard/js/batch-status.js` | Batch status UI; countdown; poll 2s when processing, 30s idle. |

---

## 6. Documentation Sync Checklist

- **MULTI_COIN_SETUP.md**: Describes multi-coin setup, 10-min cycle, batch of 5, auto-enable/disable. Code matches; note that “confidence” in that doc refers to the **readiness** metric in code for auto-enable/disable.
- **ARCHITECTURE.md**: Project structure, DB, API, strategy system, UI. Still accurate; `pair-manager.js` is mentioned but Pair Manager is removed in multi-coin (pairs are auto-enabled by batch checker).
- **Confidence threshold**: ARCHITECTURE says “90%” in one place; strategy and code use **75%** for both readiness (batch) and confidence (execute). Prefer 75% as the single source of truth unless you explicitly change it.

---

## 7. Extension Points (for fixes & enhancements)

| Need | Where / how |
|------|---------------------|
| Change TP/SL logic | Strategy `calculate_tp_sl()` (e.g. enhanced_v2) or add ATR-based in strategy. |
| Change auto-execute threshold | Strategy CONFIG `confidence_threshold` (e.g. 75). |
| Change batch auto-enable threshold | `server/app.py` `CONFIDENCE_THRESHOLD = 75.0` (readiness threshold). |
| Add a new strategy | New class in `strategies/<name>.py` extending `TradingStrategy`; auto-loaded by strategy_manager. |
| New API route | `server/app.py`. |
| Dashboard behavior | `dashboard/js/*` (init.js, data.js, ui.js, batch-status.js, pair-mode.js, etc.). |

---

## 8. Hardcoded Paths (for different environments)

- `/home/ubuntu/trading-bot/data/bot.db` (db.py)
- `/home/ubuntu/trading-bot/data/bot.log` (main.py)
- `/home/ubuntu/trading-bot/data/bot_manager.log` (bot_manager.py)
- `/home/ubuntu/trading-bot/.env` (main.py, app.py, etc.)
- `sys.path.insert(0, '/home/ubuntu/trading-bot/bot')` (app.py)

If you run elsewhere, search for `ubuntu/trading-bot` and adjust or use env/config.

---

*This document should be updated when you change code-flow, add features, or fix doc/code mismatches. Last sync: with MULTI_COIN_SETUP.md and ARCHITECTURE.md.*
