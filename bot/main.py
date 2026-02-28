"""
Bot Main — WebSocket-driven trading engine
==========================================
Flow:
  1. Connect to CoinDCX WebSocket
  2. On every new candle → run strategy.evaluate()
  3. If signal → place entry order → place TP/SL
  4. On position/order updates → update DB
  5. Every 15 min → snapshot equity to DB
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv

# Add parent to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import strategy_manager
import runtime_config
from coindcx import CoinDCXREST, CoinDCXSocket

load_dotenv(runtime_config.env_file())

# ── Logging ──────────────────────────────────
# Keep only last 2 days of log files (trade histories stay in DB)
from logging.handlers import TimedRotatingFileHandler

os.makedirs(runtime_config.data_dir(), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        TimedRotatingFileHandler(
            runtime_config.bot_log_path(),
            when="midnight",
            interval=1,
            backupCount=2,  # current + 2 days = ~2 days retention
        ),
    ],
)
logger = logging.getLogger(__name__)

# ── Parse command-line arguments ─────────────
# Only bot_manager.py should run this script: python main.py <PAIR>
# Do not run main.py directly; use systemctl start bot (which runs bot_manager.py).
INTERVAL = "5m"

# Multi-pair only: bot_manager starts one main.py per enabled pair. Global cap below applies across all pairs.
MAX_TOTAL_OPEN_TRADES = 3  # Max 3 open trades at a time (any combination of pairs)

if len(sys.argv) < 2:
    logger.error(
        "No pair argument provided. Do not run main.py directly. "
        "Start the bot service instead: systemctl start bot — it runs bot_manager.py, which starts one main.py <PAIR> per enabled pair."
    )
    sys.exit(1)

PAIR = sys.argv[1]
logger.info(f"Starting bot for pair: {PAIR}")

# ── Init ─────────────────────────────────────
API_KEY    = os.getenv("COINDCX_API_KEY")
API_SECRET = os.getenv("COINDCX_API_SECRET")

rest   = CoinDCXREST(API_KEY, API_SECRET)
socket = CoinDCXSocket(API_KEY, API_SECRET)

# Use bot_config: one active strategy and confidence threshold for all pairs
_active_strategy_key = db.get_active_strategy()
strategy_manager.strategy_manager.set_active_strategy(_active_strategy_key)
logger.info(f"Active strategy: {_active_strategy_key} | Confidence threshold: {db.get_confidence_threshold()}%")

TAKER_FEE_RATE = 0.0005  # 0.05% taker fee

# In-memory candle buffer (last 200 candles)
candle_buffer: list[dict] = []
BUFFER_SIZE = 200

# Prevent duplicate execution on the same closed candle (e.g. duplicate WebSocket events)
_last_executed_candle_ts: str | None = None

# Retry config for transient API failures
_API_RETRIES = 3
_API_BACKOFF_BASE = 1.0


def _retry_api(callable_fn, is_ok=lambda r: isinstance(r, dict) and "error" not in r):
    """Run callable up to _API_RETRIES times with exponential backoff on transient failure (error in result or exception)."""
    last_result = None
    for attempt in range(_API_RETRIES):
        try:
            result = callable_fn()
            last_result = result
            if is_ok(result):
                return result
            err = result.get("error", "") if isinstance(result, dict) else ""
            code = result.get("status_code") if isinstance(result, dict) else None
            if code and 400 <= code < 500 and code != 429:
                return result
        except Exception as e:
            last_result = {"error": str(e)}
            logger.warning(f"API call failed (attempt {attempt + 1}/{_API_RETRIES}): {e}")
        if attempt < _API_RETRIES - 1:
            wait = _API_BACKOFF_BASE * (2 ** attempt)
            logger.info(f"Retrying in {wait:.1f}s...")
            time.sleep(wait)
    return last_result


# ─────────────────────────────────────────────
#  Candle handling
# ─────────────────────────────────────────────
def _normalize_candle(raw: dict) -> dict:
    """Normalize REST or WebSocket candle to {open, high, low, close, volume, timestamp}."""
    ts = raw.get("timestamp") or raw.get("t") or raw.get("time") or ""
    return {
        "open":      float(raw.get("open", raw.get("o", 0))),
        "high":      float(raw.get("high", raw.get("h", 0))),
        "low":       float(raw.get("low", raw.get("l", 0))),
        "close":     float(raw.get("close", raw.get("c", 0))),
        "volume":    float(raw.get("volume", raw.get("v", 0))),
        "timestamp": str(ts),
        "is_closed": raw.get("is_closed", raw.get("x", True)),  # REST candles are closed
    }


def _seed_candles():
    """Load historical candles on startup so indicators have data immediately."""
    global candle_buffer
    logger.info(f"Seeding candles for {PAIR} {INTERVAL}...")
    raw_candles = rest.get_candles(PAIR, INTERVAL, limit=BUFFER_SIZE)
    if raw_candles:
        candle_buffer = [_normalize_candle(c) for c in raw_candles[-BUFFER_SIZE:]]
    else:
        candle_buffer = []
    logger.info(f"Seeded {len(candle_buffer)} candles")


def _update_candle(data: dict):
    """Called on every WebSocket candlestick event."""
    global candle_buffer
    candle = {
        "open":      float(data.get("o", 0)),
        "high":      float(data.get("h", 0)),
        "low":       float(data.get("l", 0)),
        "close":     float(data.get("c", 0)),
        "volume":    float(data.get("v", 0)),
        "timestamp": data.get("t", ""),
        "is_closed": data.get("x", False),   # True = candle closed
    }

    if candle_buffer and candle_buffer[-1]["timestamp"] == candle["timestamp"]:
        candle_buffer[-1] = candle   # update current candle
    else:
        candle_buffer.append(candle)  # new candle
        if len(candle_buffer) > BUFFER_SIZE:
            candle_buffer.pop(0)

    # Only evaluate strategy on closed candles, and only for enabled pairs
    if candle["is_closed"]:
        if not _is_pair_enabled():
            return
        logger.info(f"Closed candle for {PAIR} at {candle['close']}, running strategy")
        try:
            from datetime import datetime, timezone
            db.upsert_pair_execution_status(PAIR, last_closed_at=datetime.now(timezone.utc).isoformat(), last_error=None)
        except Exception:
            pass
        _check_paper_positions(candle)
        _run_strategy(candle["close"])


def _get_pair_config():
    try:
        all_configs = db.get_all_pair_configs()
        return next((c for c in all_configs if c["pair"] == PAIR), None)
    except Exception:
        return None


def _is_pair_enabled() -> bool:
    """True only if this pair is currently enabled (candle close / strategy run only for enabled pairs)."""
    try:
        cfg = _get_pair_config()
        if cfg is None:
            return False
        return cfg.get("enabled", 0) == 1
    except Exception:
        return False


def _get_trading_mode() -> str:
    try:
        return db.get_trading_mode()
    except Exception:
        return "REAL"


def _calc_pnl(side: str, entry_price: float, exit_price: float, quantity: float, leverage: int) -> float:
    if side == "buy":
        return (exit_price - entry_price) * quantity * leverage
    return (entry_price - exit_price) * quantity * leverage

def _resolve_trade_sizing(current_price: float, pair_config: dict | None, strategy_config: dict | None = None):
    leverage = pair_config["leverage"] if pair_config else (strategy_config.get("leverage", 5) if strategy_config else 5)
    base_quantity = pair_config["quantity"] if pair_config else (strategy_config.get("quantity", 0.001) if strategy_config else 0.001)
    inr_amount = pair_config.get("inr_amount") if pair_config else (strategy_config.get("inr_amount", 300.0) if strategy_config else 300.0)
    inr_amount = float(inr_amount) if inr_amount not in (None, "") else None

    if inr_amount and current_price > 0:
        rate = rest.get_inr_usdt_rate()
        if rate and rate > 0:
            usdt_margin = inr_amount / rate
            notional_usdt = usdt_margin * leverage
            quantity = notional_usdt / current_price
            if quantity > 0:
                return quantity, leverage, inr_amount, rate
        logger.warning("INR sizing unavailable, falling back to fixed quantity")

    return base_quantity, leverage, inr_amount, None


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _pick_most_recent_position(positions: list[dict]) -> dict | None:
    """Pick most recent position row from a list, using any available timestamp fields."""
    if not positions:
        return None

    def _ts(p: dict) -> float:
        for k in ("activation_time", "created_at", "updated_at", "timestamp"):
            raw = p.get(k)
            if raw is None or raw == "":
                continue
            try:
                val = float(raw)
                return val / 1000.0 if val > 1e10 else val
            except Exception:
                continue
        return 0.0

    return max(positions, key=_ts)


def _await_position_id(order_id: str, timeout_sec: float) -> str:
    """Poll positions until we can identify the opened position id for this PAIR/order."""
    deadline = time.monotonic() + max(0.5, timeout_sec)
    while time.monotonic() < deadline:
        try:
            positions = rest.get_positions() or []
            open_for_pair = [p for p in positions if p.get("pair") == PAIR and p.get("status") == "open"]

            if order_id:
                for p in open_for_pair:
                    for k in ("order_id", "orderId", "entry_order_id", "entryOrderId"):
                        if str(p.get(k) or "") == str(order_id):
                            return str(p.get("id") or "")

            if len(open_for_pair) == 1:
                return str(open_for_pair[0].get("id") or "")

            picked = _pick_most_recent_position(open_for_pair)
            if picked and picked.get("id"):
                return str(picked.get("id"))
        except Exception as e:
            logger.debug(f"Position poll failed: {e}")
        time.sleep(0.5)
    return ""


def _place_entry_order(pair: str, side: str, quantity: float, leverage: int, current_price: float) -> tuple[dict, str]:
    """
    Place entry order according to BOT_ENTRY_ORDER_MODE.
    Returns (order_response, label).
    """
    mode = runtime_config.entry_order_mode()
    if mode == "MARKET":
        order = _retry_api(lambda: rest.place_order(pair, side, "market_order", quantity, leverage=leverage))
        return order, "market"
    if mode == "LIMIT_THEN_MARKET":
        limit_price = round(float(current_price), 4)
        order = _retry_api(lambda: rest.place_order(pair, side, "limit_order", quantity, price=limit_price, leverage=leverage))
        return order, f"limit@{limit_price}"
    limit_price = round(float(current_price), 4)
    order = _retry_api(lambda: rest.place_order(pair, side, "limit_order", quantity, price=limit_price, leverage=leverage))
    return order, f"limit@{limit_price}"


def _get_latest_price_for_exit() -> float:
    """Best-effort price for reconciliation exit. Prefer last buffered close, else REST 1m close."""
    try:
        if candle_buffer and candle_buffer[-1].get("close"):
            return float(candle_buffer[-1]["close"])
    except Exception:
        pass
    try:
        candles = rest.get_candles(PAIR, "1m", limit=1)
        if candles:
            return float(candles[-1].get("close", candles[-1].get("c", 0)) or 0)
    except Exception:
        pass
    return 0.0


def _check_paper_positions(candle: dict):
    if _get_trading_mode() != "PAPER":
        return

    open_trades = [t for t in db.get_open_paper_trades() if t.get("pair") == PAIR]
    if not open_trades:
        return

    high = candle.get("high")
    low = candle.get("low")
    if high is None or low is None:
        return

    wallet_balance = db.get_paper_wallet_balance() or 0.0

    for t in open_trades:
        side = t.get("side")
        tp = t.get("tp_price")
        sl = t.get("sl_price")
        if tp is None or sl is None:
            continue

        hit_tp = False
        hit_sl = False

        if side == "buy":
            hit_tp = high >= tp
            hit_sl = low <= sl
        else:
            hit_tp = low <= tp
            hit_sl = high >= sl

        if not hit_tp and not hit_sl:
            continue

        # Conservative: if both hit in same candle, take SL
        exit_price = sl if hit_sl else tp

        entry_price = float(t.get("entry_price") or 0)
        quantity = float(t.get("quantity") or 0)
        leverage = int(t.get("leverage") or 1)
        entry_fee = float(t.get("fee_paid") or 0)

        # Calculate exit fee (was missing - caused NameError)
        exit_fee = exit_price * quantity * TAKER_FEE_RATE

        raw_pnl = _calc_pnl(side, entry_price, exit_price, quantity, leverage)
        net_pnl = raw_pnl - entry_fee - exit_fee
        total_fee = entry_fee + exit_fee

        db.close_paper_trade(t.get("position_id"), exit_price, net_pnl, total_fee)
        wallet_balance += net_pnl
        position_type = "LONG" if side == "buy" else "SHORT"
        logger.info(f"PAPER close {PAIR} {position_type} | pnl={net_pnl:.4f} fee={total_fee:.4f}")
        db.log_event("INFO", f"PAPER position closed {PAIR} {position_type} pnl={net_pnl:.4f} fee={total_fee:.4f}")

    db.set_paper_wallet_balance(wallet_balance)


# ── Strategy execution (single user-chosen strategy from bot_config)
# ─────────────────────────────────────────────
def _get_strategy_for_pair():
    """Use active strategy from bot_config for execution."""
    key = db.get_active_strategy()
    strat = strategy_manager.strategy_manager.get_strategy_instance(key) if key else None
    return strat or strategy_manager.strategy_manager.get_active_strategy()


def _run_strategy(current_price: float):
    global _last_executed_candle_ts
    mode = _get_trading_mode()

    # Duplicate execution guard: do not run twice for the same closed candle
    if candle_buffer:
        closed_candle_ts = candle_buffer[-1].get("timestamp") or ""
        if closed_candle_ts and closed_candle_ts == _last_executed_candle_ts:
            logger.debug(f"Skip execution for {PAIR}: already executed for candle {closed_candle_ts}")
            return

    # Global cap: only allow up to MAX_TOTAL_OPEN_TRADES (e.g. 3) open at once; when one closes, next can take its place
    open_trades = db.get_open_paper_trades() if mode == "PAPER" else db.get_open_trades()
    if len(open_trades) >= MAX_TOTAL_OPEN_TRADES:
        err = f"Max open trades ({len(open_trades)}/{MAX_TOTAL_OPEN_TRADES})"
        logger.info(f"Skip execution for {PAIR}: {err}")
        try:
            db.upsert_pair_execution_status(PAIR, last_error=err)
        except Exception:
            pass
        return

    # Per-pair limit (from strategy config; e.g. 1 per pair so we don’t stack multiple on same pair)
    pair_open_trades = [t for t in open_trades if t.get("pair") == PAIR]
    strategy_for_pair = _get_strategy_for_pair()
    if not strategy_for_pair:
        err = "No strategy (active_strategy not set or invalid)"
        logger.warning(f"Skip execution for {PAIR}: {err}")
        try:
            db.upsert_pair_execution_status(PAIR, last_error=err)
        except Exception:
            pass
        return
    max_open_trades = strategy_for_pair.get_config().get("max_open_trades", 1)
    if len(pair_open_trades) >= max_open_trades:
        err = f"Per-pair limit ({len(pair_open_trades)}/{max_open_trades})"
        logger.debug(f"Skip execution for {PAIR}: {err}")
        try:
            db.upsert_pair_execution_status(PAIR, last_error=err)
        except Exception:
            pass
        return

    # Re-entry cooldown: optional minutes to wait after last closed trade before opening again (0 = allow immediate re-entry)
    strategy_config = strategy_for_pair.get_config() if strategy_for_pair else {}
    cooldown_minutes = strategy_config.get("cooldown_minutes", 0)
    if cooldown_minutes and cooldown_minutes > 0:
        last_closed = db.get_last_closed_trade_closed_at(PAIR, paper=(mode == "PAPER"))
        if last_closed:
            try:
                from datetime import datetime, timezone
                closed_dt = datetime.fromisoformat(last_closed.replace("Z", "+00:00"))
                if closed_dt.tzinfo is None:
                    closed_dt = closed_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                elapsed_min = (now - closed_dt).total_seconds() / 60.0
                if elapsed_min < cooldown_minutes:
                    err = f"Re-entry cooldown ({elapsed_min:.1f}m < {cooldown_minutes}m)"
                    logger.info(f"Skip execution for {PAIR}: {err}")
                    try:
                        db.upsert_pair_execution_status(PAIR, last_error=err)
                    except Exception:
                        pass
                    return
            except Exception as e:
                logger.warning(f"Cooldown check failed: {e}")

    result = strategy_for_pair.evaluate(candle_buffer, return_confidence=True)

    # Handle both old format (string) and new format (dict)
    if isinstance(result, dict):
        signal = result.get("signal")
        confidence = result.get("confidence", 0.0)
        atr = result.get("atr", 0.0)
        position_size = result.get("position_size", 0.0)
        trailing_stop = result.get("trailing_stop", 0.0)
    else:
        signal = result
        confidence = 0.0
        atr = 0.0
        position_size = 0.0
        trailing_stop = 0.0

    if not signal:
        logger.debug(f"Skip execution for {PAIR}: no signal from strategy (confidence {confidence:.1f}%)")
        try:
            db.upsert_pair_execution_status(PAIR, last_confidence=confidence, last_error="No signal from strategy")
        except Exception:
            pass
        return

    threshold = db.get_confidence_threshold()
    if confidence < threshold:
        err = f"Signal rejected: confidence {confidence:.1f}% below threshold ({threshold}%)"
        logger.info(f"Signal rejected for {PAIR}: {err}")
        try:
            db.upsert_pair_execution_status(PAIR, last_confidence=confidence, last_error=err)
        except Exception:
            pass
        return

    logger.info(f"Signal: {signal} at price {current_price} | Confidence: {confidence:.1f}% (>= {threshold}%) | ATR: {atr:.4f} | Position Size: {position_size:.6f} | Trailing Stop: {trailing_stop:.2f}")
    db.log_event("INFO", f"Signal {signal} at {current_price} for {PAIR} | Confidence: {confidence:.1f}% | ATR: {atr:.4f} | Trailing Stop: {trailing_stop:.2f}%")

    # Mark this candle as "execution attempted" so duplicate WebSocket events don't double-place
    if candle_buffer:
        _last_executed_candle_ts = candle_buffer[-1].get("timestamp") or ""

    try:
        if mode == "PAPER":
            try:
                _run_paper_trade(current_price, signal, confidence, atr, position_size, trailing_stop)
                try:
                    db.upsert_pair_execution_status(PAIR, last_signal=signal, last_confidence=confidence, last_error=None)
                except Exception:
                    pass
            except Exception as e:
                err = f"Paper trade failed: {e}"
                logger.exception(f"PAPER entry failed for {PAIR}: {e}")
                try:
                    db.upsert_pair_execution_status(PAIR, last_error=err)
                except Exception:
                    pass
            return

        side = "buy" if signal == "LONG" else "sell"

        # Get pair-specific config from database; use same strategy that enabled this pair for TP/SL and config
        pair_config = _get_pair_config()
        strategy_for_pair = _get_strategy_for_pair()
        strategy_config = strategy_for_pair.get_config() if strategy_for_pair else {}
        
        quantity, leverage, inr_amount, inr_rate = _resolve_trade_sizing(current_price, pair_config, strategy_config)

        if inr_rate:
            logger.info(
                f"Using INR sizing for {PAIR}: inr={inr_amount} rate={inr_rate:.4f} lev={leverage}x qty={quantity} | Position: {signal}"
            )
        else:
            logger.info(f"Using config for {PAIR}: leverage={leverage}x, quantity={quantity} | Position: {signal}")

        # Place entry according to entry mode (LIMIT / MARKET / LIMIT_THEN_MARKET)
        entry_mode = runtime_config.entry_order_mode()
        order, order_mode_label = _place_entry_order(PAIR, side, quantity, leverage, current_price)
        if not order or order.get("error"):
            logger.error(f"Order placement failed after retries: {order}")
            db.log_event("ERROR", f"Order placement failed for {PAIR}: {order}")
            try:
                db.upsert_pair_execution_status(PAIR, last_error=f"Order placement failed: {order}")
            except Exception:
                pass
            return

        order_id = str(order.get("id", "") or "")
        position_id = str(order.get("position_id", "") or "")
        if not position_id:
            timeout = runtime_config.entry_limit_ttl_sec() if entry_mode == "LIMIT_THEN_MARKET" else 5.0
            position_id = _await_position_id(order_id, timeout_sec=timeout)

        # LIMIT_THEN_MARKET: if we still don't see a position, cancel limit and place market
        if entry_mode == "LIMIT_THEN_MARKET" and not position_id:
            try:
                if order_id:
                    rest.cancel_order(order_id)
                    logger.warning(f"Limit entry not filled within TTL; cancelled order {order_id}, switching to market entry")
            except Exception as e:
                logger.warning(f"Cancel limit order failed ({order_id}): {e}")

            order2 = _retry_api(lambda: rest.place_order(PAIR, side, "market_order", quantity, leverage=leverage))
            if not order2 or order2.get("error"):
                logger.error(f"Market fallback placement failed: {order2}")
                db.log_event("ERROR", f"Market fallback failed for {PAIR}: {order2}")
                try:
                    db.upsert_pair_execution_status(PAIR, last_error=f"Market fallback failed: {order2}")
                except Exception:
                    pass
                return
            order_id = str(order2.get("id", "") or order_id)
            position_id = str(order2.get("position_id", "") or "")
            if not position_id:
                position_id = _await_position_id(order_id, timeout_sec=5.0)
            order_mode_label = "market(fallback)"

        if not position_id:
            logger.error(f"Failed to identify position id for order {order_id}; skipping TP/SL and DB insert")
            db.log_event("ERROR", f"Failed to identify position id for {PAIR} order {order_id}")
            try:
                db.upsert_pair_execution_status(PAIR, last_error=f"No position_id for order {order_id}")
            except Exception:
                pass
            return

        logger.info(f"Entry order placed: {order_id} | {signal} {order_mode_label} | position_id={position_id}")

        # Calculate TP/SL using the strategy that enabled this pair (same as evaluate)
        strategy_for_pair = _get_strategy_for_pair()
        tp_price, sl_price = strategy_for_pair.calculate_tp_sl(current_price, signal, atr) if strategy_for_pair else (0, 0)

        # Place TP/SL (with retry on transient API failures)
        if position_id:
            tp_sl_result = _retry_api(lambda: rest.place_tp_sl(PAIR, position_id, tp_price, sl_price))
            if tp_sl_result and not tp_sl_result.get("error"):
                logger.info(f"TP={tp_price} SL={sl_price} Trailing Stop={trailing_stop:.2f} set for {signal} position {position_id}")
            else:
                logger.warning(f"TP/SL placement failed (position {position_id}): {tp_sl_result}; position remains open")
                db.log_event("WARNING", f"TP/SL failed for {PAIR} position {position_id}")

        # Save to DB
        strategy_key = db.get_active_strategy()
        db.insert_trade(
            pair=PAIR,
            side=side,
            entry_price=current_price,
            quantity=quantity,
            leverage=leverage,
            tp_price=tp_price,
            sl_price=sl_price,
            order_id=order_id,
            position_id=position_id,
            strategy_name=strategy_key or "double_ema_pullback",
            strategy_note=f"{strategy_for_pair.get_name() if strategy_for_pair else 'Unknown'} signal {signal} | Confidence: {confidence:.1f}%",
            confidence=confidence,
            atr=atr,
            position_size=position_size,
            trailing_stop=trailing_stop,
        )

    except Exception as e:
        logger.error(f"Order execution failed: {e}")
        db.log_event("ERROR", f"Order execution failed: {e}")


def _run_paper_trade(current_price: float, signal: str, confidence: float = 0.0, 
                     atr: float = 0.0, position_size: float = 0.0, trailing_stop: float = 0.0):
    side = "buy" if signal == "LONG" else "sell"
    pair_config = _get_pair_config()
    strategy_for_pair = _get_strategy_for_pair()
    strategy_config = strategy_for_pair.get_config() if strategy_for_pair else None
    quantity, leverage, inr_amount, inr_rate = _resolve_trade_sizing(current_price, pair_config, strategy_config)

    wallet_balance = db.get_paper_wallet_balance()
    if wallet_balance is None or wallet_balance <= 0:
        err = "Paper wallet not initialized or empty (switch to PAPER mode once)"
        logger.warning(f"PAPER entry skipped for {PAIR}: {err}")
        db.log_event("WARNING", "PAPER wallet not initialized or empty - switch to PAPER mode to initialize")
        try:
            db.upsert_pair_execution_status(PAIR, last_error=err)
        except Exception:
            pass
        return

    # Calculate TP/SL using the strategy that enabled this pair
    tp_price, sl_price = strategy_for_pair.calculate_tp_sl(current_price, signal, atr) if strategy_for_pair else (0, 0)

    # Simulate order placement
    order_id = f"PAPER-{int(time.time() * 1000)}"
    position_id = f"PAPER-POS-{int(time.time() * 1000)}"
    entry_fee = current_price * quantity * TAKER_FEE_RATE

    if entry_fee > wallet_balance:
        err = "PAPER wallet insufficient for fee"
        logger.warning(f"PAPER entry skipped for {PAIR}: {err}")
        db.log_event("WARNING", "PAPER wallet insufficient for fee")
        try:
            db.upsert_pair_execution_status(PAIR, last_error=err)
        except Exception:
            pass
        return

    db.set_paper_wallet_balance(wallet_balance - entry_fee)

    strategy_key = db.get_active_strategy()
    db.insert_paper_trade(
        pair=PAIR,
        side=side,
        entry_price=current_price,
        quantity=quantity,
        leverage=leverage,
        tp_price=tp_price,
        sl_price=sl_price,
        fee_paid=entry_fee,
        order_id=order_id,
        position_id=position_id,
        strategy_name=strategy_key or "double_ema_pullback",
        strategy_note=f"{strategy_for_pair.get_name() if strategy_for_pair else 'Unknown'} signal {signal} | Confidence: {confidence:.1f}%",
        confidence=confidence,
        atr=atr,
        position_size=position_size,
        trailing_stop=trailing_stop,
    )

    if inr_rate:
        logger.info(
            f"PAPER entry {PAIR} | {signal} inr={inr_amount} rate={inr_rate:.4f} qty={quantity} lev={leverage} fee={entry_fee:.4f} | Confidence: {confidence:.1f}% | ATR: {atr:.4f} | Trailing Stop: {trailing_stop:.2f}"
        )
        db.log_event(
            "INFO",
            f"PAPER entry {PAIR} {signal} inr={inr_amount} rate={inr_rate:.4f} qty={quantity} lev={leverage} | Confidence: {confidence:.1f}%",
        )
    else:
        logger.info(f"PAPER entry {PAIR} | {signal} qty={quantity} lev={leverage} fee={entry_fee:.4f} | Confidence: {confidence:.1f}% | ATR: {atr:.4f} | Trailing Stop: {trailing_stop:.2f}")
        db.log_event("INFO", f"PAPER entry {PAIR} {signal} qty={quantity} lev={leverage} | Confidence: {confidence:.1f}%")


# ─────────────────────────────────────────────
#  WebSocket event handlers
# ─────────────────────────────────────────────
def on_candlestick(data):
    try:
        _update_candle(data)
    except Exception as e:
        logger.error(f"Candle handler error: {e}")


def on_position_update(data):
    """Called when a position is opened/closed/updated."""
    try:
        if _get_trading_mode() == "PAPER":
            return
        pos_id = data.get("id", "")
        status = data.get("status", "")

        if status in ("closed", "liquidated"):
            exit_price = float(data.get("exit_price", 0))
            pnl        = float(data.get("realized_pnl", 0))
            db.close_trade(pos_id, exit_price, pnl)
            logger.info(f"Position {pos_id} closed | PnL={pnl}")
            db.log_event("INFO", f"Position closed PnL={pnl}")
    except Exception as e:
        logger.error(f"Position update handler error: {e}")


def on_order_update(data):
    """Called when an order status changes (TP/SL triggered etc.)"""
    order_id = data.get("id", "")
    status   = data.get("status", "")
    logger.info(f"Order {order_id} → {status}")


# ─────────────────────────────────────────────
#  Equity snapshot thread
# ─────────────────────────────────────────────
def _equity_snapshot_loop():
    while True:
        try:
            mode = _get_trading_mode()
            if mode == "PAPER":
                balance = db.get_paper_wallet_balance()
                if balance is not None:
                    db.snapshot_paper_equity(balance)
            else:
                wallet = rest.get_wallet()
                balance = 0.0
                # CoinDCX futures wallet API returns a list of wallet objects
                if isinstance(wallet, list):
                    # Prefer INR (platform margin), else USDT
                    pref = None
                    for w in wallet:
                        if not isinstance(w, dict):
                            continue
                        curr = str(w.get("currency_short_name") or w.get("currency") or "").upper()
                        if curr == "INR":
                            pref = w
                            break
                        if curr == "USDT" and pref is None:
                            pref = w
                    w = pref or (wallet[0] if wallet else None)
                    if isinstance(w, dict):
                        balance = _safe_float(
                            w.get("available_balance")
                            or w.get("wallet_balance")
                            or w.get("total_balance")
                            or w.get("balance"),
                            0.0,
                        )
                elif isinstance(wallet, dict):
                    balance = _safe_float(wallet.get("balance") or wallet.get("available_balance"), 0.0)
                db.snapshot_equity(balance)
        except Exception as e:
            logger.warning(f"Equity snapshot failed: {e}")
        time.sleep(900)   # every 15 minutes


# ─────────────────────────────────────────────
#  Position reconciliation (REAL mode)
# ─────────────────────────────────────────────
def _normalize_side(raw) -> str:
    s = str(raw or "").lower()
    if s in ("buy", "long"):
        return "buy"
    if s in ("sell", "short"):
        return "sell"
    return "buy"


def _position_reconcile_loop():
    """
    Keep DB trades consistent with exchange positions.
    Fixes cases where WebSocket 'position_update' is missed and DB stays 'open' forever.
    """
    interval = runtime_config.position_reconcile_interval_sec()
    while True:
        try:
            if _get_trading_mode() != "REAL":
                time.sleep(interval)
                continue

            # If creds are missing, do not attempt reconciliation (avoid closing DB trades by accident)
            if not API_KEY or not API_SECRET:
                time.sleep(interval)
                continue

            db_open = [t for t in db.get_open_trades() if t.get("pair") == PAIR]
            db_pos_ids = {str(t.get("position_id")) for t in db_open if t.get("position_id")}

            positions = rest.get_positions() or []
            ex_open = [p for p in positions if p.get("pair") == PAIR and p.get("status") == "open"]
            ex_ids = {str(p.get("id")) for p in ex_open if p.get("id")}

            # Close DB trades that no longer exist on exchange
            for t in db_open:
                pos_id = str(t.get("position_id") or "")
                if not pos_id:
                    continue
                if pos_id in ex_ids:
                    continue
                exit_price = _get_latest_price_for_exit()
                entry_price = _safe_float(t.get("entry_price"), 0.0)
                quantity = _safe_float(t.get("quantity"), 0.0)
                leverage = int(_safe_float(t.get("leverage"), 1))
                side = _normalize_side(t.get("side"))
                pnl = _calc_pnl(side, entry_price, exit_price, quantity, leverage) if exit_price else 0.0
                db.close_trade(pos_id, exit_price, pnl)
                logger.warning(f"Reconciler closed stale DB trade {PAIR} pos={pos_id} exit={exit_price} pnl={pnl:.4f}")
                db.log_event("WARNING", f"Reconciler closed stale DB trade {PAIR} pos={pos_id} pnl={pnl:.4f}")

            # Insert external open positions that are missing in DB (so caps/limits remain safe)
            for p in ex_open:
                pos_id = str(p.get("id") or "")
                if not pos_id or pos_id in db_pos_ids:
                    continue
                active_pos = _safe_float(p.get("active_pos"), 0.0)
                qty = abs(active_pos) if active_pos else abs(_safe_float(p.get("quantity"), 0.0))
                if qty <= 0:
                    continue
                side = "buy" if active_pos > 0 else "sell" if active_pos < 0 else _normalize_side(p.get("side"))
                entry_price = _safe_float(p.get("avg_price") or p.get("entry_price"), 0.0)
                lev = int(_safe_float(p.get("leverage"), 1))
                db.insert_trade(
                    pair=PAIR,
                    side=side,
                    entry_price=entry_price,
                    quantity=qty,
                    leverage=lev,
                    tp_price=None,
                    sl_price=None,
                    order_id="",
                    position_id=pos_id,
                    strategy_name="external",
                    strategy_note="Inserted by reconciler (position existed on exchange)",
                    confidence=0.0,
                    atr=0.0,
                    position_size=0.0,
                    trailing_stop=0.0,
                )
                logger.warning(f"Reconciler inserted external position into DB {PAIR} pos={pos_id} side={side} qty={qty}")
                db.log_event("WARNING", f"Reconciler inserted external position {PAIR} pos={pos_id}")

        except Exception as e:
            logger.warning(f"Position reconciliation failed: {e}")
        time.sleep(interval)


# ─────────────────────────────────────────────
#  5m timer fallback when WebSocket doesn't send closed candles
# ─────────────────────────────────────────────
def _seconds_until_next_5m_utc():
    """Seconds until next 5m boundary (UTC)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    sec = now.timestamp()
    return 300 - (int(sec) % 300) - (sec % 1)


def _run_on_5m_timer():
    """Run strategy at each 5m boundary using REST last-closed candle (fallback when WS has no closed flag). Only for enabled pairs."""
    from datetime import datetime, timezone
    while True:
        try:
            wait = _seconds_until_next_5m_utc()
            time.sleep(wait + 3)
            # Only check candle close and run strategy for enabled pairs
            if not _is_pair_enabled():
                continue
            raw_list = rest.get_candles(PAIR, INTERVAL, limit=5)
            if not raw_list or len(raw_list) < 2:
                logger.warning(f"5m timer: not enough candles from REST for {PAIR}")
                continue
            # Last closed = second-to-last (newest is often still open)
            closed_raw = raw_list[-2]
            candle = _normalize_candle(closed_raw)
            candle["is_closed"] = True
            global candle_buffer
            if candle_buffer and candle_buffer[-1].get("timestamp") == candle["timestamp"]:
                candle_buffer[-1] = candle
            else:
                candle_buffer.append(candle)
                if len(candle_buffer) > BUFFER_SIZE:
                    candle_buffer.pop(0)
            logger.info(f"Closed candle for {PAIR} at {candle['close']}, running strategy (5m timer fallback)")
            try:
                db.upsert_pair_execution_status(PAIR, last_closed_at=datetime.now(timezone.utc).isoformat(), last_error=None)
            except Exception:
                pass
            _check_paper_positions(candle)
            _run_strategy(candle["close"])
        except Exception as e:
            logger.exception(f"5m timer fallback failed for {PAIR}: {e}")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main():
    logger.info("=== Trading Bot Starting ===")

    # Init DB
    os.makedirs(runtime_config.data_dir(), exist_ok=True)
    db.init_db()
    try:
        db.cleanup_bot_log_older_than_days()
    except Exception as e:
        logger.warning(f"Bot log cleanup skipped: {e}")

    # Only run for enabled pairs; exit immediately if this pair is disabled (avoids BTC-only process)
    if not _is_pair_enabled():
        logger.warning(f"Pair {PAIR} is not enabled. Exiting. (Bot manager starts one process per enabled pair only.)")
        db.log_event("INFO", f"Exiting: {PAIR} is not enabled")
        sys.exit(0)

    db.log_event("INFO", "Bot started")

    # Seed candles
    _seed_candles()

    # Start equity snapshot thread
    t = threading.Thread(target=_equity_snapshot_loop, daemon=True)
    t.start()

    # Start 5m timer fallback so we run strategy even when WebSocket doesn't send closed candles
    timer_thread = threading.Thread(target=_run_on_5m_timer, daemon=True)
    timer_thread.start()
    logger.info("5m timer fallback started (runs strategy at each 5m close using REST)")

    # Reconcile DB open trades vs exchange positions (REAL mode only)
    reconcile_thread = threading.Thread(target=_position_reconcile_loop, daemon=True)
    reconcile_thread.start()
    logger.info(f"Position reconciler started (every {runtime_config.position_reconcile_interval_sec():.0f}s)")

    # Register socket callbacks
    socket.on("candlestick", on_candlestick)
    socket.on("position_update", on_position_update)
    socket.on("order_update", on_order_update)

    # Connect with automatic reconnection
    logger.info(f"Connecting WebSocket for {PAIR} {INTERVAL}...")
    
    # Reconnection loop with exponential backoff
    retry_delay = 1  # Start with 1 second
    max_retry_delay = 60  # Max 60 seconds between retries
    
    while True:
        try:
            socket.connect(PAIR, INTERVAL)
            logger.info("WebSocket connected successfully")
            db.log_event("INFO", "WebSocket connected")
            retry_delay = 1  # Reset delay on successful connection
            
            # Block and wait for events
            socket.wait()
            
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            db.log_event("INFO", "Bot stopped by user")
            break
            
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            db.log_event("ERROR", f"WebSocket error: {e}")
            
            # Disconnect before reconnecting
            try:
                socket.disconnect()
            except Exception:
                pass
            
            # Wait before reconnecting (exponential backoff)
            logger.warning(f"Reconnecting in {retry_delay} seconds...")
            time.sleep(retry_delay)
            
            # Increase delay for next retry (exponential backoff)
            retry_delay = min(retry_delay * 2, max_retry_delay)



if __name__ == "__main__":
    main()
