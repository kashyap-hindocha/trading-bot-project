"""
Bot Main — Multi-Pair WebSocket-driven trading engine
======================================================
Flow:
  1. Load enabled pairs from pair_config database
  2. Connect to CoinDCX WebSocket for each pair
  3. On every new candle → run strategy.evaluate() with confidence
  4. If signal AND confidence >= 90% → place entry order → place TP/SL
  5. On position/order updates → update DB
  6. Every 15 min → snapshot equity to DB
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

# ── Config ───────────────────────────────────
CONFIDENCE_THRESHOLD = 90.0  # Only trade if confidence >= 90%
INTERVAL = "5m"
BUFFER_SIZE = 200
TAKER_FEE_RATE = 0.0005  # 0.05% taker fee

# ── Init ─────────────────────────────────────
API_KEY    = os.getenv("COINDCX_API_KEY")
API_SECRET = os.getenv("COINDCX_API_SECRET")

rest   = CoinDCXREST(API_KEY, API_SECRET)
socket = CoinDCXSocket(API_KEY, API_SECRET)

# Per-pair data: {pair: {"candles": [...], "config": {...}}}
pair_data = {}


# ─────────────────────────────────────────────
#  Initialization Functions
# ─────────────────────────────────────────────
def _init_pair_data():
    """Load pairs based on mode (SINGLE/MULTI) and initialize their state."""
    global pair_data
    try:
        # Initialize pair mode if not set
        db.init_pair_mode_if_missing()
        
        # Get current pair mode
        mode_config = db.get_pair_mode()
        pair_mode = mode_config.get("pair_mode", "MULTI")
        selected_pair = mode_config.get("selected_pair")
        
        logger.info(f"Pair mode: {pair_mode}" + (f" (selected: {selected_pair})" if selected_pair else ""))
        
        if pair_mode == "SINGLE":
            # Single pair mode - load only the selected pair
            if not selected_pair:
                logger.error("SINGLE mode selected but no pair specified. Defaulting to MULTI mode.")
                db.set_pair_mode("MULTI")
                enabled_pairs = db.get_enabled_pairs()
            else:
                # Get config for the selected pair
                pair_config = db.get_pair_config(selected_pair)
                if pair_config:
                    enabled_pairs = [pair_config]
                    logger.info(f"Trading SINGLE pair: {selected_pair}")
                else:
                    # Pair not found, create default config
                    logger.warning(f"Config not found for {selected_pair}, creating default")
                    db.upsert_pair_config(selected_pair, 1, 5, 0.001, 300.0)
                    pair_config = db.get_pair_config(selected_pair)
                    enabled_pairs = [pair_config] if pair_config else []
        else:
            # Multi pair mode - load all enabled pairs
            enabled_pairs = db.get_enabled_pairs()
            logger.info(f"Trading MULTI pairs: {len(enabled_pairs)} pairs enabled")
        
        # Initialize pair_data dictionary
        pair_data = {
            p["pair"]: {
                "candles": [],
                "config": p,
                "open_trades": []
            }
            for p in enabled_pairs
        }
        
        logger.info(f"Initialized {len(pair_data)} pairs: {list(pair_data.keys())}")
        return list(pair_data.keys())
    except Exception as e:
        logger.error(f"Error loading pair configs: {e}")
        return []


def _seed_candles_for_pair(pair: str):
    """Load historical candles for a pair on startup."""
    try:
        logger.info(f"Seeding candles for {pair} {INTERVAL}...")
        candles = rest.get_candles(pair, INTERVAL, limit=BUFFER_SIZE)
        pair_data[pair]["candles"] = candles[-BUFFER_SIZE:]
        logger.info(f"Seeded {len(pair_data[pair]['candles'])} candles for {pair}")
    except Exception as e:
        logger.error(f"Error seeding candles for {pair}: {e}")


def _seed_all_candles():
    """Seed candles for all enabled pairs."""
    for pair in pair_data.keys():
        _seed_candles_for_pair(pair)


# ─────────────────────────────────────────────
#  Candle Handling
# ─────────────────────────────────────────────
def _update_candle(pair: str, data: dict):
    """Called on every WebSocket candlestick event for a specific pair."""
    if pair not in pair_data:
        logger.warning(f"Received candle for unknown pair {pair}")
        return

    candle_buffer = pair_data[pair]["candles"]
    
    candle = {
        "open":      float(data.get("o", 0)),
        "high":      float(data.get("h", 0)),
        "low":       float(data.get("l", 0)),
        "close":     float(data.get("c", 0)),
        "volume":    float(data.get("v", 0)),
        "timestamp": data.get("t", ""),
        "is_closed": data.get("x", False),
    }

    if candle_buffer and candle_buffer[-1]["timestamp"] == candle["timestamp"]:
        candle_buffer[-1] = candle  # update current candle
    else:
        candle_buffer.append(candle)  # new candle
        if len(candle_buffer) > BUFFER_SIZE:
            candle_buffer.pop(0)

    # Only evaluate strategy on closed candles
    if candle["is_closed"]:
        _check_paper_positions(pair, candle)
        _run_strategy(pair, candle["close"])


# ─────────────────────────────────────────────
#  Trading Logic
# ─────────────────────────────────────────────
def _get_trading_mode() -> str:
    try:
        return db.get_trading_mode()
    except Exception:
        return "REAL"


def _get_open_trades_for_pair(pair: str) -> list:
    """Get all open trades for a specific pair."""
    mode = _get_trading_mode()
    if mode == "PAPER":
        return [t for t in db.get_open_paper_trades() if t.get("pair") == pair]
    return [t for t in db.get_open_trades() if t.get("pair") == pair]


def _calc_pnl(side: str, entry_price: float, exit_price: float, quantity: float, leverage: int) -> float:
    """Calculate PnL for a trade."""
    if side == "buy":
        return (exit_price - entry_price) * quantity * leverage
    return (entry_price - exit_price) * quantity * leverage


def _resolve_trade_sizing(pair: str, current_price: float):
    pair_config = pair_data[pair]["config"]
    leverage = pair_config.get("leverage", strategy.CONFIG["leverage"])
    base_quantity = pair_config.get("quantity", strategy.CONFIG["quantity"])
    inr_amount = pair_config.get("inr_amount", strategy.CONFIG.get("inr_amount"))
    inr_amount = float(inr_amount) if inr_amount not in (None, "") else None

    if inr_amount and current_price > 0:
        rate = rest.get_inr_usdt_rate()
        if rate and rate > 0:
            usdt_margin = inr_amount / rate
            notional_usdt = usdt_margin * leverage
            quantity = notional_usdt / current_price
            if quantity > 0:
                return quantity, leverage, inr_amount, rate
        logger.warning(f"{pair} INR sizing unavailable, falling back to fixed quantity")

    return base_quantity, leverage, inr_amount, None


def _check_paper_positions(pair: str, candle: dict):
    """Check if paper trading positions hit TP/SL and close them."""
    if _get_trading_mode() != "PAPER":
        return

    open_trades = _get_open_trades_for_pair(pair)
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
        logger.info(f"PAPER close {pair} | pnl={net_pnl:.4f} fee={total_fee:.4f}")
        db.log_event("INFO", f"PAPER position closed {pair} pnl={net_pnl:.4f} fee={total_fee:.4f}")

    db.set_paper_wallet_balance(wallet_balance)


def _run_strategy(pair: str, current_price: float):
    """Evaluate strategy for a pair and place trade if confidence >= 90%."""
    mode = _get_trading_mode()
    max_open = strategy.CONFIG["max_open_trades"]

    # Check max open trades limit globally
    all_open_trades = db.get_open_paper_trades() if mode == "PAPER" else db.get_open_trades()
    if len(all_open_trades) >= max_open:
        return

    candle_buffer = pair_data[pair]["candles"]
    
    # Get signal with confidence
    result = strategy.evaluate(candle_buffer, return_confidence=True)
    if not result or result["signal"] is None:
        return

    signal = result["signal"]
    confidence = result["confidence"]

    # Only execute if confidence >= threshold
    if confidence < CONFIDENCE_THRESHOLD:
        logger.debug(f"{pair} signal {signal} rejected: confidence {confidence:.1f}% < {CONFIDENCE_THRESHOLD}%")
        return

    logger.info(f"Signal: {signal} at price {current_price} for {pair} | Confidence: {confidence:.1f}%")
    db.log_event("INFO", f"Signal {signal} at {current_price} for {pair} | Confidence: {confidence:.1f}%")

    try:
        if mode == "PAPER":
            _run_paper_trade(pair, current_price, signal, confidence)
            return

        side       = "buy" if signal == "BUY" else "sell"
        order_type = "market_order"
        
        # Get pair-specific config
        quantity, leverage, inr_amount, inr_rate = _resolve_trade_sizing(pair, current_price)

        if inr_rate:
            logger.info(
                f"Using INR sizing for {pair}: inr={inr_amount} rate={inr_rate:.4f} lev={leverage}x qty={quantity}"
            )
        else:
            logger.info(f"Using config for {pair}: leverage={leverage}x, quantity={quantity}")

        # Place entry order
        order = rest.place_order(pair, side, order_type, quantity, leverage=leverage)
        order_id = order.get("id", "")
        logger.info(f"Entry order placed: {order_id}")

        # Small delay to let position register
        time.sleep(1)

        # Get position ID from open positions
        positions = rest.get_positions()
        position_id = ""
        for p in positions:
            if p.get("pair") == pair:
                position_id = p.get("id", "")
                break

        # Calculate TP/SL
        tp_price, sl_price = strategy.calculate_tp_sl(current_price, signal)

        # Place TP/SL
        if position_id:
            rest.place_tp_sl(pair, position_id, tp_price, sl_price)
            logger.info(f"TP={tp_price} SL={sl_price} set for position {position_id}")

        # Save to DB
        db.insert_trade(
            pair=pair,
            side=side,
            entry_price=current_price,
            quantity=quantity,
            leverage=leverage,
            tp_price=tp_price,
            sl_price=sl_price,
            order_id=order_id,
            position_id=position_id,
            strategy_note=f"EMA crossover signal {signal}",
            confidence=confidence,
        )

    except Exception as e:
        logger.error(f"Order execution failed for {pair}: {e}")
        db.log_event("ERROR", f"Order execution failed for {pair}: {e}")


def _run_paper_trade(pair: str, current_price: float, signal: str, confidence: float):
    """Execute paper trade for a pair."""
    side = "buy" if signal == "BUY" else "sell"
    quantity, leverage, inr_amount, inr_rate = _resolve_trade_sizing(pair, current_price)

    wallet_balance = db.get_paper_wallet_balance()
    if wallet_balance is None or wallet_balance <= 0:
        logger.warning(f"PAPER wallet not initialized or empty for {pair}")
        db.log_event("WARNING", f"PAPER wallet not initialized or empty for {pair}")
        return

    # Calculate TP/SL
    tp_price, sl_price = strategy.calculate_tp_sl(current_price, signal)

    # Simulate order placement
    order_id = f"PAPER-{int(time.time() * 1000)}"
    position_id = f"PAPER-POS-{int(time.time() * 1000)}"
    entry_fee = current_price * quantity * TAKER_FEE_RATE

    if entry_fee > wallet_balance:
        logger.warning(f"PAPER wallet insufficient for fee on {pair}")
        db.log_event("WARNING", f"PAPER wallet insufficient for fee on {pair}")
        return

    db.set_paper_wallet_balance(wallet_balance - entry_fee)

    db.insert_paper_trade(
        pair=pair,
        side=side,
        entry_price=current_price,
        quantity=quantity,
        leverage=leverage,
        tp_price=tp_price,
        sl_price=sl_price,
        fee_paid=entry_fee,
        order_id=order_id,
        position_id=position_id,
        strategy_note=f"EMA crossover signal {signal}",
        confidence=confidence,
    )

    if inr_rate:
        logger.info(
            f"PAPER entry {pair} | side={side} inr={inr_amount} rate={inr_rate:.4f} qty={quantity} lev={leverage} fee={entry_fee:.4f} conf={confidence:.1f}%"
        )
        db.log_event(
            "INFO",
            f"PAPER entry {pair} side={side} inr={inr_amount} rate={inr_rate:.4f} qty={quantity} lev={leverage} conf={confidence:.1f}%",
        )
    else:
        logger.info(f"PAPER entry {pair} | side={side} qty={quantity} lev={leverage} fee={entry_fee:.4f} conf={confidence:.1f}%")
        db.log_event("INFO", f"PAPER entry {pair} side={side} qty={quantity} lev={leverage} conf={confidence:.1f}%")


# ─────────────────────────────────────────────
#  WebSocket Event Handlers
# ─────────────────────────────────────────────
def on_candlestick(data):
    """Handle candlestick updates for any pair."""
    try:
        pair = data.get("pair")
        _update_candle(pair, data)
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
    """Called when an order status changes."""
    try:
        order_id = data.get("id", "")
        status   = data.get("status", "")
        logger.info(f"Order {order_id} → {status}")
    except Exception as e:
        logger.error(f"Order update handler error: {e}")


# ─────────────────────────────────────────────
#  Equity Snapshot Thread
# ─────────────────────────────────────────────
def _equity_snapshot_loop():
    """Periodically snapshot account equity."""
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
#  Active Pairs Tracking
# ─────────────────────────────────────────────
def _update_active_pairs_tracking():
    """Update a tracking file showing which pairs are currently being traded."""
    try:
        active_pairs = []
        mode = _get_trading_mode()
        
        for pair in pair_data.keys():
            open_trades = _get_open_trades_for_pair(pair)
            if open_trades:
                active_pairs.append({
                    "pair": pair,
                    "open_trades": len(open_trades),
                    "mode": mode,
                    "timestamp": datetime.utcnow().isoformat()
                })
        
        # Store in database or log for UI to read
        logger.info(f"Active trading pairs: {[p['pair'] for p in active_pairs]}")
    except Exception as e:
        logger.warning(f"Active pairs tracking failed: {e}")


def _active_pairs_tracking_loop():
    """Periodically update active pairs tracking."""
    while True:
        try:
            _update_active_pairs_tracking()
        except Exception as e:
            logger.warning(f"Active pairs tracking loop error: {e}")
        time.sleep(60)  # every minute


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main():
    logger.info("=== Multi-Pair Trading Bot Starting ===")

    # Init DB
    os.makedirs("/home/ubuntu/trading-bot/data", exist_ok=True)
    db.init_db()
    db.log_event("INFO", "Multi-pair bot started")

    # Load enabled pairs
    enabled_pairs = _init_pair_data()
    if not enabled_pairs:
        logger.error("No enabled pairs found. Exiting.")
        return

    # Seed candles for all pairs
    _seed_all_candles()

    # Start equity snapshot thread
    t1 = threading.Thread(target=_equity_snapshot_loop, daemon=True)
    t1.start()

    # Start active pairs tracking thread
    t2 = threading.Thread(target=_active_pairs_tracking_loop, daemon=True)
    t2.start()

    # Register socket callbacks
    socket.on("candlestick", on_candlestick)
    socket.on("position_update", on_position_update)
    socket.on("order_update", on_order_update)

    # Connect WebSocket for all enabled pairs
    logger.info(f"Connecting WebSocket for {len(enabled_pairs)} pairs {INTERVAL}...")
    for pair in enabled_pairs:
        socket.connect(pair, INTERVAL)
    
    logger.info("All pairs subscribed. Waiting for data...")
    socket.wait()


if __name__ == "__main__":
    main()
