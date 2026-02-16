"""
Strategy Framework
==================
Define YOUR strategy here. The bot calls:
    signal = strategy.evaluate(candles)

Returns:
    "BUY"  — open a long
    "SELL" — open a short
    None   — do nothing

Candles format (list of dicts, newest last):
    { open, high, low, close, volume, timestamp }

CONFIG block at the top is what you tune.
Everything below compute_indicators() is the signal logic — edit freely.
"""

import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  CONFIG — edit these values to tune strategy
# ─────────────────────────────────────────────
CONFIG = {
    "pair":          "B-BTC_USDT",      # Trading pair
    "interval":      "5m",           # Candle interval
    "leverage":      5,              # Leverage (1 = no leverage)
    "quantity":      0.001,          # Order size in base currency (BTC)
    "tp_pct":        0.015,          # Take profit %  (1.5%)
    "sl_pct":        0.008,          # Stop loss %    (0.8%)
    "max_open_trades": 1,            # Max simultaneous open positions

    # ── Add your indicator params below ──────
    "ema_fast":      9,
    "ema_slow":      21,
    "rsi_period":    14,
    "rsi_overbought": 70,
    "rsi_oversold":   30,
}


# ─────────────────────────────────────────────
#  Indicator helpers
# ─────────────────────────────────────────────
def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_indicators(candles: list[dict]) -> dict:
    """
    Compute all indicators from candles.
    Add your own indicators here.
    """
    closes = [c["close"] for c in candles]

    ema_fast_series = _ema(closes, CONFIG["ema_fast"])
    ema_slow_series = _ema(closes, CONFIG["ema_slow"])
    rsi             = _rsi(closes, CONFIG["rsi_period"])

    return {
        "ema_fast":    ema_fast_series[-1] if ema_fast_series else None,
        "ema_slow":    ema_slow_series[-1] if ema_slow_series else None,
        "ema_fast_prev": ema_fast_series[-2] if len(ema_fast_series) >= 2 else None,
        "ema_slow_prev": ema_slow_series[-2] if len(ema_slow_series) >= 2 else None,
        "rsi":         rsi,
        "last_close":  closes[-1] if closes else None,
    }


# ─────────────────────────────────────────────
#  SIGNAL LOGIC — edit this function
# ─────────────────────────────────────────────
def evaluate(candles: list[dict]) -> str | None:
    """
    Main entry point called by the bot on every new candle.

    Current logic: EMA crossover + RSI filter
    ─────────────────────────────────────────
    BUY  when fast EMA crosses above slow EMA AND RSI < overbought
    SELL when fast EMA crosses below slow EMA AND RSI > oversold

    Replace or extend this logic with your own strategy.
    """
    if len(candles) < CONFIG["ema_slow"] + 5:
        return None   # not enough data yet

    ind = compute_indicators(candles)

    if None in (ind["ema_fast"], ind["ema_slow"],
                ind["ema_fast_prev"], ind["ema_slow_prev"]):
        return None

    # EMA crossover detection
    crossed_up   = (ind["ema_fast_prev"] <= ind["ema_slow_prev"] and
                    ind["ema_fast"]       >  ind["ema_slow"])

    crossed_down = (ind["ema_fast_prev"] >= ind["ema_slow_prev"] and
                    ind["ema_fast"]       <  ind["ema_slow"])

    if crossed_up and ind["rsi"] < CONFIG["rsi_overbought"]:
        logger.info(f"BUY signal | EMA fast={ind['ema_fast']:.2f} slow={ind['ema_slow']:.2f} RSI={ind['rsi']}")
        return "BUY"

    if crossed_down and ind["rsi"] > CONFIG["rsi_oversold"]:
        logger.info(f"SELL signal | EMA fast={ind['ema_fast']:.2f} slow={ind['ema_slow']:.2f} RSI={ind['rsi']}")
        return "SELL"

    return None


# ─────────────────────────────────────────────
#  TP / SL price calculation
# ─────────────────────────────────────────────
def calculate_tp_sl(entry_price: float, side: str) -> tuple[float, float]:
    """Returns (tp_price, sl_price) based on CONFIG percentages."""
    tp_pct = CONFIG["tp_pct"]
    sl_pct = CONFIG["sl_pct"]
    if side == "BUY":
        tp = round(entry_price * (1 + tp_pct), 4)
        sl = round(entry_price * (1 - sl_pct), 4)
    else:
        tp = round(entry_price * (1 - tp_pct), 4)
        sl = round(entry_price * (1 + sl_pct), 4)
    return tp, sl
