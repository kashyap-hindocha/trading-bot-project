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
import strategy
from coindcx import CoinDCXREST, CoinDCXSocket

load_dotenv("/home/ubuntu/trading-bot/.env")

# ── Logging ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/ubuntu/trading-bot/data/bot.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── Parse command-line arguments ─────────────
PAIR     = strategy.CONFIG["pair"]      # Default pair
INTERVAL = strategy.CONFIG["interval"]

if len(sys.argv) > 1:
    # Allow overriding pair from command line: python main.py B-ETH_USDT
    PAIR = sys.argv[1]
    logger.info(f"Using pair from command line: {PAIR}")

# ── Init ─────────────────────────────────────
API_KEY    = os.getenv("COINDCX_API_KEY")
API_SECRET = os.getenv("COINDCX_API_SECRET")

rest   = CoinDCXREST(API_KEY, API_SECRET)
socket = CoinDCXSocket(API_KEY, API_SECRET)

TAKER_FEE_RATE = 0.0005  # 0.05% taker fee

# In-memory candle buffer (last 200 candles)
candle_buffer: list[dict] = []
BUFFER_SIZE = 200


# ─────────────────────────────────────────────
#  Candle handling
# ─────────────────────────────────────────────
def _seed_candles():
    """Load historical candles on startup so indicators have data immediately."""
    global candle_buffer
    logger.info(f"Seeding candles for {PAIR} {INTERVAL}...")
    candles = rest.get_candles(PAIR, INTERVAL, limit=BUFFER_SIZE)
    candle_buffer = candles[-BUFFER_SIZE:]
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

    # Only evaluate strategy on closed candles
    if candle["is_closed"]:
        _check_paper_positions(candle)
        _run_strategy(candle["close"])


def _get_pair_config():
    try:
        all_configs = db.get_all_pair_configs()
        return next((c for c in all_configs if c["pair"] == PAIR), None)
    except Exception:
        return None


def _get_trading_mode() -> str:
    try:
        return db.get_trading_mode()
    except Exception:
        return "REAL"


def _calc_pnl(side: str, entry_price: float, exit_price: float, quantity: float, leverage: int) -> float:
    if side == "buy":
        return (exit_price - entry_price) * quantity * leverage
    return (entry_price - exit_price) * quantity * leverage


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
        exit_fee = exit_price * quantity * TAKER_FEE_RATE

        raw_pnl = _calc_pnl(side, entry_price, exit_price, quantity, leverage)
        net_pnl = raw_pnl - entry_fee - exit_fee
        total_fee = entry_fee + exit_fee

        db.close_paper_trade(t.get("position_id"), exit_price, net_pnl, total_fee)
        wallet_balance += net_pnl
        logger.info(f"PAPER close {PAIR} | pnl={net_pnl:.4f} fee={total_fee:.4f}")
        db.log_event("INFO", f"PAPER position closed {PAIR} pnl={net_pnl:.4f} fee={total_fee:.4f}")

    db.set_paper_wallet_balance(wallet_balance)


# ── Strategy execution
# ─────────────────────────────────────────────
def _run_strategy(current_price: float):
    mode = _get_trading_mode()

    # Check max open trades limit
    open_trades = db.get_open_paper_trades() if mode == "PAPER" else db.get_open_trades()
    if len(open_trades) >= strategy.CONFIG["max_open_trades"]:
        return

    result = strategy.evaluate(candle_buffer, return_confidence=True)
    
    # Handle both old format (string) and new format (dict)
    if isinstance(result, dict):
        signal = result.get("signal")
        confidence = result.get("confidence", 0.0)
        auto_execute = result.get("auto_execute", False)
    else:
        signal = result
        confidence = 0.0
        auto_execute = False
    
    if not signal:
        return

    logger.info(f"Signal: {signal} at price {current_price} | Confidence: {confidence:.1f}% | Auto-execute: {auto_execute}")
    db.log_event("INFO", f"Signal {signal} at {current_price} for {PAIR} | Confidence: {confidence:.1f}%")

    try:
        if mode == "PAPER":
            _run_paper_trade(current_price, signal, confidence)
            return

        side       = "buy" if signal == "BUY" else "sell"
        order_type = "market_order"
        
        # Get pair-specific config from database, fallback to strategy defaults
        pair_config = _get_pair_config()
        quantity = pair_config["quantity"] if pair_config else strategy.CONFIG["quantity"]
        leverage = pair_config["leverage"] if pair_config else strategy.CONFIG["leverage"]
        
        logger.info(f"Using config for {PAIR}: leverage={leverage}x, quantity={quantity} | Confidence: {confidence:.1f}%")

        # Place entry order
        order = rest.place_order(PAIR, side, order_type, quantity, leverage=leverage)
        order_id = order.get("id", "")
        logger.info(f"Entry order placed: {order_id} | Auto-execute: {auto_execute}")

        # Small delay to let position register
        time.sleep(1)

        # Get position ID from open positions
        positions = rest.get_positions()
        position_id = ""
        for p in positions:
            if p.get("pair") == PAIR:
                position_id = p.get("id", "")
                break

        # Calculate TP/SL
        tp_price, sl_price = strategy.calculate_tp_sl(current_price, signal)

        # Place TP/SL
        if position_id:
            rest.place_tp_sl(PAIR, position_id, tp_price, sl_price)
            logger.info(f"TP={tp_price} SL={sl_price} set for position {position_id}")

        # Save to DB
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
            strategy_note=f"EMA crossover signal {signal} | Confidence: {confidence:.1f}% | Auto-execute: {auto_execute}",
        )

    except Exception as e:
        logger.error(f"Order execution failed: {e}")
        db.log_event("ERROR", f"Order execution failed: {e}")


def _run_paper_trade(current_price: float, signal: str, confidence: float = 0.0):
    side = "buy" if signal == "BUY" else "sell"
    pair_config = _get_pair_config()
    quantity = pair_config["quantity"] if pair_config else strategy.CONFIG["quantity"]
    leverage = pair_config["leverage"] if pair_config else strategy.CONFIG["leverage"]

    wallet_balance = db.get_paper_wallet_balance()
    if wallet_balance is None or wallet_balance <= 0:
        logger.warning("PAPER wallet not initialized or empty")
        db.log_event("WARNING", "PAPER wallet not initialized or empty")
        return

    # Calculate TP/SL
    tp_price, sl_price = strategy.calculate_tp_sl(current_price, signal)

    # Simulate order placement
    order_id = f"PAPER-{int(time.time() * 1000)}"
    position_id = f"PAPER-POS-{int(time.time() * 1000)}"
    entry_fee = current_price * quantity * TAKER_FEE_RATE

    if entry_fee > wallet_balance:
        logger.warning("PAPER wallet insufficient for fee")
        db.log_event("WARNING", "PAPER wallet insufficient for fee")
        return

    db.set_paper_wallet_balance(wallet_balance - entry_fee)

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
        strategy_note=f"EMA crossover signal {signal} | Confidence: {confidence:.1f}%",
    )

    logger.info(f"PAPER entry {PAIR} | side={side} qty={quantity} lev={leverage} fee={entry_fee:.4f} | Confidence: {confidence:.1f}%")
    db.log_event("INFO", f"PAPER entry {PAIR} side={side} qty={quantity} lev={leverage} | Confidence: {confidence:.1f}%")


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
#  Main
# ─────────────────────────────────────────────
def main():
    logger.info("=== Trading Bot Starting ===")

    # Init DB
    os.makedirs("/home/ubuntu/trading-bot/data", exist_ok=True)
    db.init_db()
    db.log_event("INFO", "Bot started")

    # Seed candles
    _seed_candles()

    # Start equity snapshot thread
    t = threading.Thread(target=_equity_snapshot_loop, daemon=True)
    t.start()

    # Register socket callbacks
    socket.on("candlestick", on_candlestick)
    socket.on("position_update", on_position_update)
    socket.on("order_update", on_order_update)

    # Connect and block
    logger.info(f"Connecting WebSocket for {PAIR} {INTERVAL}...")
    socket.connect(PAIR, INTERVAL)
    socket.wait()


if __name__ == "__main__":
    main()
