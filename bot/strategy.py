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
    "max_open_trades": 5,            # Max simultaneous open positions
    "auto_execute":  True,           # Auto-execute trades above confidence threshold
    "confidence_threshold": 90.0,    # Confidence threshold for auto-execute (0-100%)

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
        "ema_fast_series": ema_fast_series,
        "ema_slow_series": ema_slow_series,
    }


def calculate_confidence(ind: dict, position_type: str) -> float:
    """
    Calculate strategy confidence (0-100%) based on indicator alignment.
    
    Factors:
    - EMA crossover (40% weight)
    - RSI alignment (40% weight)
    - Trend strength - EMA separation (20% weight)
    
    Args:
        position_type: "LONG" or "SHORT"
    """
    confidence = 0.0
    
    if not ind.get("ema_fast") or not ind.get("ema_slow"):
        return 0.0
    
    # 1. EMA Crossover (40% weight) - proximity to crossover
    ema_diff = abs(ind["ema_fast"] - ind["ema_slow"])
    ema_separation = abs(ind["ema_slow_series"][-1] - ind["ema_fast_series"][-1]) if len(ind.get("ema_slow_series", [])) > 0 else 0.01
    crossover_proximity = max(0, 1 - (ema_diff / max(ema_separation, 0.01)))
    
    if position_type == "LONG":
        # Fresh LONG crossover = higher confidence
        crossed_up = (ind["ema_fast_prev"] <= ind["ema_slow_prev"] and
                      ind["ema_fast"] > ind["ema_slow"])
        confidence += 40 if crossed_up else (crossover_proximity * 40)
    else:
        # Fresh SHORT crossover = higher confidence
        crossed_down = (ind["ema_fast_prev"] >= ind["ema_slow_prev"] and
                        ind["ema_fast"] < ind["ema_slow"])
        confidence += 40 if crossed_down else (crossover_proximity * 40)
    
    # 2. RSI Alignment (40% weight)
    rsi = ind["rsi"]
    if position_type == "LONG":
        # LONG: RSI should be below overbought, ideally in oversold
        if rsi < CONFIG["rsi_oversold"]:
            confidence += 40  # Ideal oversold condition
        elif rsi < CONFIG["rsi_overbought"]:
            rsi_alignment = (CONFIG["rsi_overbought"] - rsi) / CONFIG["rsi_overbought"]
            confidence += 40 * rsi_alignment
    else:
        # SHORT: RSI should be above oversold, ideally in overbought
        if rsi > CONFIG["rsi_overbought"]:
            confidence += 40  # Ideal overbought condition
        elif rsi > CONFIG["rsi_oversold"]:
            rsi_alignment = (rsi - CONFIG["rsi_oversold"]) / (100 - CONFIG["rsi_oversold"])
            confidence += 40 * rsi_alignment
    
    # 3. Trend Strength - EMA Separation (20% weight)
    if ema_separation > 0:
        last_close = ind["last_close"]
        trend_strength = min(1.0, ema_separation / (last_close * 0.02))  # normalize by 2% of price
        confidence += 20 * trend_strength
    
    return min(100.0, round(confidence, 1))


# ─────────────────────────────────────────────
#  SIGNAL LOGIC — edit this function
# ─────────────────────────────────────────────
def evaluate(candles: list[dict], return_confidence: bool = True) -> str | None | dict:
    """
    Main entry point called by the bot on every new candle.

    Current logic: EMA crossover + RSI filter
    ─────────────────────────────────────────
    BUY  when fast EMA crosses above slow EMA AND RSI < overbought
    SELL when fast EMA crosses below slow EMA AND RSI > oversold

    Args:
        candles: List of candle dicts with OHLCV data
        return_confidence: If True, returns {"signal": str, "confidence": float} (default: True)
                          If False, returns just signal string (backward compatible)

    Returns:
        dict: {"signal": str, "confidence": float, "auto_execute": bool}
        or str: "BUY"/"SELL"/None (if return_confidence=False)
    """
    if len(candles) < CONFIG["ema_slow"] + 5:
        if return_confidence:
            return {"signal": None, "confidence": 0.0, "auto_execute": False}
        return None

    ind = compute_indicators(candles)

    if None in (ind["ema_fast"], ind["ema_slow"],
                ind["ema_fast_prev"], ind["ema_slow_prev"]):
        if return_confidence:
            return {"signal": None, "confidence": 0.0, "auto_execute": False}
        return None

    # EMA crossover detection
    crossed_up   = (ind["ema_fast_prev"] <= ind["ema_slow_prev"] and
                    ind["ema_fast"]       >  ind["ema_slow"])

    crossed_down = (ind["ema_fast_prev"] >= ind["ema_slow_prev"] and
                    ind["ema_fast"]       <  ind["ema_slow"])

    signal = None
    confidence = 0.0
    auto_execute = False

    if crossed_up and ind["rsi"] < CONFIG["rsi_overbought"]:
        signal = "LONG"
        confidence = calculate_confidence(ind, "LONG")
        auto_execute = CONFIG["auto_execute"] and confidence >= CONFIG["confidence_threshold"]
        logger.info(f"LONG signal | EMA fast={ind['ema_fast']:.2f} slow={ind['ema_slow']:.2f} RSI={ind['rsi']} | Confidence: {confidence:.1f}% | Auto-execute: {auto_execute}")

    if crossed_down and ind["rsi"] > CONFIG["rsi_oversold"]:
        signal = "SHORT"
        confidence = calculate_confidence(ind, "SHORT")
        auto_execute = CONFIG["auto_execute"] and confidence >= CONFIG["confidence_threshold"]
        logger.info(f"SHORT signal | EMA fast={ind['ema_fast']:.2f} slow={ind['ema_slow']:.2f} RSI={ind['rsi']} | Confidence: {confidence:.1f}% | Auto-execute: {auto_execute}")

    if return_confidence:
        return {"signal": signal, "confidence": confidence, "auto_execute": auto_execute}
    return signal


# ─────────────────────────────────────────────
#  TP / SL price calculation
# ─────────────────────────────────────────────
def calculate_tp_sl(entry_price: float, position_type: str) -> tuple[float, float]:
    """Returns (tp_price, sl_price) based on CONFIG percentages.
    
    Args:
        position_type: "LONG" or "SHORT"
    """
    tp_pct = CONFIG["tp_pct"]
    sl_pct = CONFIG["sl_pct"]
    if position_type == "LONG":
        tp = round(entry_price * (1 + tp_pct), 4)
        sl = round(entry_price * (1 - sl_pct), 4)
    else:
        tp = round(entry_price * (1 - tp_pct), 4)
        sl = round(entry_price * (1 + sl_pct), 4)
    return tp, sl
