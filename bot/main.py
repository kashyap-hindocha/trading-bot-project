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
from coindcx import CoinDCXREST, CoinDCXSocket

load_dotenv("/home/ubuntu/trading-bot/.env")

# ── Logging ──────────────────────────────────
# Keep only last 2 days of log files (trade histories stay in DB)
from logging.handlers import TimedRotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        TimedRotatingFileHandler(
            "/home/ubuntu/trading-bot/data/bot.log",
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

        side       = "buy" if signal == "LONG" else "sell"
        # Limit order at current price: avoid paying more (buy) or receiving less (sell) than current price.
        order_type = "limit_order"
        limit_price = round(float(current_price), 4)

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

        # Place entry order as limit at current price (with retry on transient API failures)
        order = _retry_api(lambda: rest.place_order(PAIR, side, order_type, quantity, price=limit_price, leverage=leverage))
        if not order or order.get("error"):
            logger.error(f"Order placement failed after retries: {order}")
            db.log_event("ERROR", f"Order placement failed for {PAIR}: {order}")
            return
        order_id = order.get("id", "")
        logger.info(f"Entry order placed: {order_id} | {signal} limit @ {limit_price}")

        # Try to get position ID from order response first
        position_id = order.get("position_id", "")
        
        # If not in order response, poll positions with retry logic
        if not position_id:
            max_retries = 5
            retry_count = 0
            
            while retry_count < max_retries and not position_id:
                time.sleep(0.5)  # Wait for position to register
                
                try:
                    positions = rest.get_positions()
                    for p in positions:
                        if p.get("pair") == PAIR and p.get("status") == "open":
                            # Additional check: match order_id if available
                            if order_id and p.get("order_id") == order_id:
                                position_id = p.get("id", "")
                                break
                            # Fallback: just match pair (less safe but works)
                            elif not position_id:
                                position_id = p.get("id", "")
                    
                    if position_id:
                        logger.info(f"Position ID found: {position_id} (retry {retry_count + 1})")
                        break
                        
                except Exception as e:
                    logger.warning(f"Error fetching positions (retry {retry_count + 1}): {e}")
                
                retry_count += 1
            
            if not position_id:
                logger.error(f"Failed to get position ID after {max_retries} retries")
                db.log_event("ERROR", f"Failed to get position ID for order {order_id}")

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
            strategy_name=strategy_key or "enhanced_v2",
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
        strategy_name=strategy_key or "enhanced_v2",
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
                wallet  = rest.get_wallet()
                balance = float(wallet.get("balance", 0))
                db.snapshot_equity(balance)
        except Exception as e:
            logger.warning(f"Equity snapshot failed: {e}")
        time.sleep(900)   # every 15 minutes


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
    os.makedirs("/home/ubuntu/trading-bot/data", exist_ok=True)
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
