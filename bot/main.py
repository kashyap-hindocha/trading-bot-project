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

# ── Parse command-line arguments ─────────────
PAIR     = strategy.CONFIG["pair"]      # Default pair
INTERVAL = strategy.CONFIG["interval"]

if len(sys.argv) > 1:
    # Allow overriding pair from command line: python main.py B-ETH_USDT
    PAIR = sys.argv[1]
    logger.info(f"Using pair from command line: {PAIR}")

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

# ── Init ─────────────────────────────────────
API_KEY    = os.getenv("COINDCX_API_KEY")
API_SECRET = os.getenv("COINDCX_API_SECRET")

rest   = CoinDCXREST(API_KEY, API_SECRET)
socket = CoinDCXSocket(API_KEY, API_SECRET)

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
        _run_strategy(candle["close"])


# ── Strategy execution
# ─────────────────────────────────────────────
def _run_strategy(current_price: float):
    # Check max open trades limit
    open_trades = db.get_open_trades()
    if len(open_trades) >= strategy.CONFIG["max_open_trades"]:
        return

    signal = strategy.evaluate(candle_buffer)
    if not signal:
        return

    logger.info(f"Signal: {signal} at price {current_price}")
    db.log_event("INFO", f"Signal {signal} at {current_price} for {PAIR}")

    try:
        side       = "buy" if signal == "BUY" else "sell"
        order_type = "market_order"
        
        # Get pair-specific config from database, fallback to strategy defaults
        pair_config = None
        try:
            all_configs = db.get_all_pair_configs()
            pair_config = next((c for c in all_configs if c["pair"] == PAIR), None)
        except:
            pass
        
        quantity = pair_config["quantity"] if pair_config else strategy.CONFIG["quantity"]
        leverage = pair_config["leverage"] if pair_config else strategy.CONFIG["leverage"]
        
        logger.info(f"Using config for {PAIR}: leverage={leverage}x, quantity={quantity}")

        # Place entry order
        order = rest.place_order(PAIR, side, order_type, quantity, leverage=leverage)
        order_id = order.get("id", "")
        logger.info(f"Entry order placed: {order_id}")

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
            strategy_note=f"EMA crossover signal {signal}",
        )

    except Exception as e:
        logger.error(f"Order execution failed: {e}")
        db.log_event("ERROR", f"Order execution failed: {e}")


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
