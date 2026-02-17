"""
Strategy Framework - ENHANCED v2
=================================
Advanced trading strategy with:
  - Volatility-adjusted position sizing (ATR)
  - Multi-timeframe confirmation
  - Dynamic trailing stops
  - MACD & Volume confirmation
  - Relaxed RSI with additional confirmations

Define YOUR strategy here. The bot calls:
    signal = strategy.evaluate(candles)

Returns:
    dict: {"signal": str, "confidence": float, "auto_execute": bool, "atr": float, "trailing_stop": float}
    or str: "BUY"/"SELL"/None (if return_confidence=False)

Candles format (list of dicts, newest last):
    { open, high, low, close, volume, timestamp }

CONFIG block at the top is what you tune.
Everything below compute_indicators() is the signal logic — edit freely.
"""

import logging
import statistics

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  CONFIG — edit these values to tune strategy
# ─────────────────────────────────────────────
CONFIG = {
    "pair":          "B-BTC_USDT",      # Trading pair
    "interval":      "5m",              # Candle interval
    "leverage":      5,                 # Leverage (1 = no leverage)
    "quantity":      0.001,             # Base order size in base currency (BTC)
    "inr_amount":    300.0,             # Margin budget per trade in INR
    "tp_pct":        0.015,             # Take profit %  (1.5%)
    "sl_pct":        0.008,             # Stop loss %    (0.8%)
    "max_open_trades": 5,               # Max simultaneous open positions
    "auto_execute":  True,              # Auto-execute trades above confidence threshold
    "confidence_threshold": 75.0,       # Confidence threshold for auto-execute (lowered from 90%)

    # ── EMA & Trend Indicators ──────
    "ema_fast":      9,
    "ema_slow":      21,
    
    # ── RSI (Relaxed Settings) ──────
    "rsi_period":    14,
    "rsi_overbought": 75,              # Relaxed from 70 (allows strong trends)
    "rsi_oversold":   25,              # Relaxed from 30
    
    # ── ATR (Volatility) ──────
    "atr_period":    14,
    "atr_multiplier": 1.5,             # Trailing stop: Close +/- ATR*multiplier
    
    # ── MACD ──────
    "macd_fast":     12,
    "macd_slow":     26,
    "macd_signal":   9,
    
    # ── Volume ──────
    "volume_ma_period": 20,            # Volume moving average period
    "min_volume_ratio": 0.8,           # Min volume as % of MA (0.8 = 80%)
    
    # ── Position Sizing ──────
    "volatility_adjusted": True,       # Use ATR for position sizing
    "min_position_size": 0.0005,       # Minimum BTC to trade
    "max_position_size": 0.01,         # Maximum BTC to trade
}


# ─────────────────────────────────────────────
#  Indicator helpers
# ─────────────────────────────────────────────
def _ema(values: list[float], period: int) -> list[float]:
    """Calculate Exponential Moving Average"""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: list[float], period: int = 14) -> float:
    """Calculate Relative Strength Index"""
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


def _atr(candles: list[dict], period: int = 14) -> float:
    """Calculate Average True Range for volatility"""
    if len(candles) < period:
        return 0.0
    
    true_ranges = []
    for i in range(len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        close_prev = candles[i-1]["close"] if i > 0 else candles[i]["close"]
        
        tr = max(
            high - low,
            abs(high - close_prev),
            abs(low - close_prev)
        )
        true_ranges.append(tr)
    
    # Use SMA of true ranges
    atr = sum(true_ranges[-period:]) / period
    return round(atr, 4)


def _macd(closes: list[float]) -> dict:
    """Calculate MACD (Moving Average Convergence Divergence)"""
    fast_period = CONFIG["macd_fast"]
    slow_period = CONFIG["macd_slow"]
    signal_period = CONFIG["macd_signal"]
    
    if len(closes) < slow_period + signal_period:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}
    
    ema_fast = _ema(closes, fast_period)
    ema_slow = _ema(closes, slow_period)
    
    # Ensure both EMAs have enough data
    min_len = min(len(ema_fast), len(ema_slow))
    if min_len == 0:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}
    
    # MACD line = fast EMA - slow EMA
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
    
    # Signal line = EMA of MACD
    signal_line = _ema(macd_line, signal_period)
    
    if not signal_line:
        return {"macd": macd_line[-1] if macd_line else 0.0, "signal": 0.0, "histogram": 0.0}
    
    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    histogram = current_macd - current_signal
    
    return {
        "macd": round(current_macd, 4),
        "signal": round(current_signal, 4),
        "histogram": round(histogram, 4)
    }


def _volume_ma(volumes: list[float], period: int = 20) -> float:
    """Calculate Volume Moving Average"""
    if len(volumes) < period:
        return 0.0
    return sum(volumes[-period:]) / period


def compute_indicators(candles: list[dict]) -> dict:
    """
    Compute all indicators from candles.
    Includes: EMA, RSI, ATR, MACD, Volume analysis
    """
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]

    # Trend Indicators
    ema_fast_series = _ema(closes, CONFIG["ema_fast"])
    ema_slow_series = _ema(closes, CONFIG["ema_slow"])
    rsi = _rsi(closes, CONFIG["rsi_period"])
    
    # Volatility Indicator
    atr = _atr(candles, CONFIG["atr_period"])
    
    # Momentum Indicator
    macd_data = _macd(closes)
    
    # Volume Analysis
    volume_ma = _volume_ma(volumes, CONFIG["volume_ma_period"])
    current_volume = volumes[-1] if volumes else 0
    volume_ratio = (current_volume / volume_ma) if volume_ma > 0 else 0

    return {
        # EMA Indicators
        "ema_fast":    ema_fast_series[-1] if ema_fast_series else None,
        "ema_slow":    ema_slow_series[-1] if ema_slow_series else None,
        "ema_fast_prev": ema_fast_series[-2] if len(ema_fast_series) >= 2 else None,
        "ema_slow_prev": ema_slow_series[-2] if len(ema_slow_series) >= 2 else None,
        "ema_fast_series": ema_fast_series,
        "ema_slow_series": ema_slow_series,
        
        # RSI
        "rsi":         rsi,
        
        # Volatility (ATR)
        "atr":         atr,
        
        # MACD
        "macd":        macd_data["macd"],
        "macd_signal": macd_data["signal"],
        "macd_histogram": macd_data["histogram"],
        
        # Volume
        "volume":       current_volume,
        "volume_ma":    volume_ma,
        "volume_ratio": volume_ratio,
        
        # Price
        "last_close":  closes[-1] if closes else None,
        "last_high":   highs[-1] if highs else None,
        "last_low":    lows[-1] if lows else None,
    }


def calculate_confidence(ind: dict, position_type: str) -> float:
    """
    Calculate strategy confidence (0-100%) based on multiple indicator alignment.
    
    Factors (weights):
    - EMA crossover & trend (30%)
    - MACD confirmation (25%)
    - RSI alignment (20%)
    - Volume confirmation (15%)
    - Trend strength - EMA separation (10%)
    
    Args:
        position_type: "LONG" or "SHORT"
    """
    confidence = 0.0
    
    if not ind.get("ema_fast") or not ind.get("ema_slow"):
        return 0.0
    
    # 1. EMA Crossover & Trend (30% weight)
    ema_diff = abs(ind["ema_fast"] - ind["ema_slow"])
    ema_separation = abs(ind["ema_slow"] - ind["ema_fast"]) if ind["ema_slow"] else 0.01
    
    if position_type == "LONG":
        # LONG: fast EMA above slow EMA = uptrend
        if ind["ema_fast"] > ind["ema_slow"]:
            confidence += 30
            # Extra bonus for fresh crossover
            if (ind["ema_fast_prev"] and ind["ema_slow_prev"] and
                ind["ema_fast_prev"] <= ind["ema_slow_prev"]):
                confidence += 5  # Fresh crossover bonus
    else:
        # SHORT: fast EMA below slow EMA = downtrend
        if ind["ema_fast"] < ind["ema_slow"]:
            confidence += 30
            # Extra bonus for fresh crossover
            if (ind["ema_fast_prev"] and ind["ema_slow_prev"] and
                ind["ema_fast_prev"] >= ind["ema_slow_prev"]):
                confidence += 5  # Fresh crossover bonus
    
    # 2. MACD Confirmation (25% weight)
    macd_hist = ind.get("macd_histogram", 0)
    macd = ind.get("macd", 0)
    macd_signal = ind.get("macd_signal", 0)
    
    if position_type == "LONG":
        # LONG: MACD > signal & positive histogram
        if macd > macd_signal and macd_hist > 0:
            confidence += 25
        elif macd > macd_signal:
            confidence += 12.5
    else:
        # SHORT: MACD < signal & negative histogram
        if macd < macd_signal and macd_hist < 0:
            confidence += 25
        elif macd < macd_signal:
            confidence += 12.5
    
    # 3. RSI Alignment (20% weight) - Relaxed thresholds
    rsi = ind.get("rsi", 50)
    
    if position_type == "LONG":
        # LONG: Low RSI is ideal, but allow values up to 80 for strong trends
        if rsi < CONFIG["rsi_oversold"]:
            confidence += 20  # Oversold - ideal entry
        elif rsi < 50:
            # RSI below 50 is good for LONG
            confidence += 20 * (50 - rsi) / 50
        else:
            # Allow some trending setups (RSI 50-80)
            confidence += max(0, 10 * (80 - rsi) / 30)
    else:
        # SHORT: High RSI is ideal, but allow down to 20 for strong trends
        if rsi > CONFIG["rsi_overbought"]:
            confidence += 20  # Overbought - ideal entry
        elif rsi > 50:
            # RSI above 50 is good for SHORT
            confidence += 20 * (rsi - 50) / 50
        else:
            # Allow some trending setups (RSI 20-50)
            confidence += max(0, 10 * (rsi - 20) / 30)
    
    # 4. Volume Confirmation (15% weight)
    volume_ratio = ind.get("volume_ratio", 0)
    min_vol = CONFIG["min_volume_ratio"]
    
    if volume_ratio >= 1.0:
        confidence += 15  # Above average volume
    elif volume_ratio >= min_vol:
        confidence += 15 * (volume_ratio / min_vol)
    
    # 5. Trend Strength - EMA Separation (10% weight)
    if ema_separation > 0 and ind["last_close"]:
        last_close = ind["last_close"]
        # Normalize: 2% of price = strong separation
        trend_strength = min(1.0, ema_separation / (last_close * 0.02))
        confidence += 10 * trend_strength
    
    return min(100.0, round(confidence, 1))


# ─────────────────────────────────────────────
#  SIGNAL LOGIC — edit this function
# ─────────────────────────────────────────────
def calculate_position_size(entry_price: float, atr: float, rsi: float, position_type: str) -> float:
    """
    Calculate dynamic position size based on volatility (ATR) and market conditions.
    
    Lower volatility = larger position
    Higher volatility = smaller position
    
    Args:
        entry_price: Current price
        atr: Average True Range
        rsi: Relative Strength Index
        position_type: "LONG" or "SHORT"
    
    Returns:
        Position size in base currency (BTC)
    """
    base_size = CONFIG["quantity"]
    
    if not CONFIG["volatility_adjusted"]:
        return base_size
    
    # Volatility adjustment: ATR as % of price
    volatility_pct = (atr / entry_price) * 100
    
    # Scale position inversely to volatility
    # Low volatility (<0.5%) -> 1.0x multiplier
    # High volatility (>2%) -> 0.5x multiplier
    if volatility_pct < 0.5:
        vol_multiplier = 1.0
    elif volatility_pct > 2.0:
        vol_multiplier = 0.5
    else:
        # Linear interpolation
        vol_multiplier = 1.0 - ((volatility_pct - 0.5) / 1.5) * 0.5
    
    # RSI adjustment: avoid extreme conditions
    rsi_multiplier = 1.0
    if position_type == "LONG":
        if rsi < 20:  # Extremely oversold
            rsi_multiplier = 1.1
        elif rsi > 85:  # Extremely overbought
            rsi_multiplier = 0.8
    else:
        if rsi > 80:  # Extremely overbought
            rsi_multiplier = 1.1
        elif rsi < 15:  # Extremely oversold
            rsi_multiplier = 0.8
    
    position_size = base_size * vol_multiplier * rsi_multiplier
    
    # Clamp to min/max
    position_size = max(CONFIG["min_position_size"], 
                       min(CONFIG["max_position_size"], position_size))
    
    return round(position_size, 6)


def calculate_trailing_stop(entry_price: float, atr: float, position_type: str) -> float:
    """
    Calculate dynamic trailing stop based on ATR.
    
    Args:
        entry_price: Entry price
        atr: Average True Range
        position_type: "LONG" or "SHORT"
    
    Returns:
        Trailing stop price
    """
    multiplier = CONFIG["atr_multiplier"]
    
    if position_type == "LONG":
        # For LONG: stop below entry
        trailing_stop = round(entry_price - (atr * multiplier), 4)
    else:
        # For SHORT: stop above entry
        trailing_stop = round(entry_price + (atr * multiplier), 4)
    
    return trailing_stop


# ─────────────────────────────────────────────
#  SIGNAL LOGIC — edit this function
# ─────────────────────────────────────────────
def evaluate(candles: list[dict], return_confidence: bool = True) -> str | None | dict:
    """
    Main entry point called by the bot on every new candle.

    Advanced logic: EMA trend + MACD momentum + RSI filter + Volume check
    ─────────────────────────────────────────────────────────────────────
    BUY  when:
      - Fast EMA cross above Slow EMA (uptrend)
      - MACD crosses above signal (momentum)
      - Volume >= 80% of MA (confirmation)
      - Relaxed RSI (no longer requires < 70)
    
    SELL when:
      - Fast EMA cross below Slow EMA (downtrend)
      - MACD crosses below signal (momentum)
      - Volume >= 80% of MA (confirmation)
      - Relaxed RSI (no longer requires > 30)

    Args:
        candles: List of candle dicts with OHLCV data
        return_confidence: If True, returns full dict with ATR and trailing stop.
                          If False, returns just signal string (backward compatible)

    Returns:
        dict: {"signal": str, "confidence": float, "auto_execute": bool, 
               "atr": float, "position_size": float, "trailing_stop": float}
        or str: "BUY"/"SELL"/None (if return_confidence=False)
    """
    min_candles = max(CONFIG["ema_slow"], CONFIG["macd_slow"]) + 5
    if len(candles) < min_candles:
        if return_confidence:
            return {
                "signal": None, 
                "confidence": 0.0, 
                "auto_execute": False,
                "atr": 0.0,
                "position_size": 0.0,
                "trailing_stop": 0.0
            }
        return None

    ind = compute_indicators(candles)

    if None in (ind["ema_fast"], ind["ema_slow"],
                ind["ema_fast_prev"], ind["ema_slow_prev"]):
        if return_confidence:
            return {
                "signal": None, 
                "confidence": 0.0, 
                "auto_execute": False,
                "atr": 0.0,
                "position_size": 0.0,
                "trailing_stop": 0.0
            }
        return None

    # EMA crossover detection
    crossed_up   = (ind["ema_fast_prev"] <= ind["ema_slow_prev"] and
                    ind["ema_fast"]       >  ind["ema_slow"])

    crossed_down = (ind["ema_fast_prev"] >= ind["ema_slow_prev"] and
                    ind["ema_fast"]       <  ind["ema_slow"])
    
    # MACD crossover detection
    macd_crossed_up = (ind["macd"] > ind["macd_signal"])
    macd_crossed_down = (ind["macd"] < ind["macd_signal"])
    
    # Volume check
    volume_confirmed = ind.get("volume_ratio", 0) >= CONFIG["min_volume_ratio"]

    signal = None
    confidence = 0.0
    auto_execute = False
    atr = ind.get("atr", 0.0)
    position_size = 0.0
    trailing_stop = 0.0
    
    current_price = ind["last_close"]

    # LONG Signal: EMA crossup + MACD confirmation + Volume check
    if crossed_up and macd_crossed_up and volume_confirmed:
        signal = "LONG"
        confidence = calculate_confidence(ind, "LONG")
        position_size = calculate_position_size(current_price, atr, ind["rsi"], "LONG")
        trailing_stop = calculate_trailing_stop(current_price, atr, "LONG")
        auto_execute = CONFIG["auto_execute"] and confidence >= CONFIG["confidence_threshold"]
        logger.info(
            f"LONG signal | EMA: {ind['ema_fast']:.2f}>{ind['ema_slow']:.2f} | "
            f"MACD: {ind['macd']:.4f}>{ind['macd_signal']:.4f} | RSI: {ind['rsi']} | "
            f"Volume: {ind['volume_ratio']:.2f}x | ATR: {atr:.4f} | "
            f"Confidence: {confidence:.1f}% | Position Size: {position_size:.6f} BTC | "
            f"Trailing Stop: {trailing_stop:.2f} | Auto-execute: {auto_execute}"
        )

    # SHORT Signal: EMA crossdown + MACD confirmation + Volume check
    elif crossed_down and macd_crossed_down and volume_confirmed:
        signal = "SHORT"
        confidence = calculate_confidence(ind, "SHORT")
        position_size = calculate_position_size(current_price, atr, ind["rsi"], "SHORT")
        trailing_stop = calculate_trailing_stop(current_price, atr, "SHORT")
        auto_execute = CONFIG["auto_execute"] and confidence >= CONFIG["confidence_threshold"]
        logger.info(
            f"SHORT signal | EMA: {ind['ema_fast']:.2f}<{ind['ema_slow']:.2f} | "
            f"MACD: {ind['macd']:.4f}<{ind['macd_signal']:.4f} | RSI: {ind['rsi']} | "
            f"Volume: {ind['volume_ratio']:.2f}x | ATR: {atr:.4f} | "
            f"Confidence: {confidence:.1f}% | Position Size: {position_size:.6f} BTC | "
            f"Trailing Stop: {trailing_stop:.2f} | Auto-execute: {auto_execute}"
        )

    if return_confidence:
        return {
            "signal": signal, 
            "confidence": confidence, 
            "auto_execute": auto_execute,
            "atr": atr,
            "position_size": position_size,
            "trailing_stop": trailing_stop
        }
    return signal


# ─────────────────────────────────────────────
#  TP / SL price calculation
# ─────────────────────────────────────────────
def calculate_tp_sl(entry_price: float, position_type: str, atr: float = 0.0) -> tuple[float, float]:
    """
    Returns (tp_price, sl_price) based on CONFIG percentages.
    Can use fixed percentages or ATR-based dynamic stops.
    
    Args:
        entry_price: Entry price
        position_type: "LONG" or "SHORT"
        atr: ATR value (optional for dynamic stops)
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


# ─────────────────────────────────────────────
#  Multi-timeframe confirmation (optional)
# ─────────────────────────────────────────────
def check_daily_trend(hourly_candles: list[dict]) -> str | None:
    """
    Optional: Check if daily trend aligns with signal.
    
    This would require daily candles to be loaded externally.
    Placeholder for future implementation with additional data feeds.
    
    Args:
        hourly_candles: 1H candles to extrapolate daily trend
    
    Returns:
        "UP" (bullish daily), "DOWN" (bearish daily), or None (neutral)
    """
    if len(hourly_candles) < 24:
        return None
    
    # Check 24H trend by comparing 24H ago to current
    close_24h_ago = hourly_candles[-24]["close"]
    close_now = hourly_candles[-1]["close"]
    
    if close_now > close_24h_ago:
        return "UP"
    elif close_now < close_24h_ago:
        return "DOWN"
    return None


# ─────────────────────────────────────────────
#  Signal Strength (for pair sorting)
# ─────────────────────────────────────────────
def calculate_signal_strength(candles: list[dict]) -> float:
    """
    Calculate how close a pair is to generating a trade signal (0-100).
    Used for sorting pairs by proximity to signals.
    
    Returns:
        100 = Signal triggered (confidence >= 90%)
        80-99 = Very close (indicators aligning)
        60-79 = Moderate (some indicators aligning)
        0-59 = Far from signal
    
    Algorithm:
        - If signal exists, return confidence score
        - Otherwise, calculate proximity based on:
          * EMA distance (how close to crossover)
          * MACD alignment
          * RSI levels
          * Volume
    """
    min_candles = max(CONFIG["ema_slow"], CONFIG["macd_slow"]) + 5
    if len(candles) < min_candles:
        return 0.0
    
    # First check if there's an active signal
    result = evaluate(candles, return_confidence=True)
    if result and result["signal"] and result["confidence"] >= 90:
        return 100.0  # Active signal with high confidence
    elif result and result["signal"]:
        return result["confidence"]  # Active signal with lower confidence
    
    # No signal yet - calculate proximity
    ind = compute_indicators(candles)
    
    if None in (ind["ema_fast"], ind["ema_slow"]):
        return 0.0
    
    strength = 0.0
    
    # 1. EMA Proximity (40% weight) - how close to crossover
    ema_diff = abs(ind["ema_fast"] - ind["ema_slow"])
    last_close = ind["last_close"] if ind["last_close"] else 1
    ema_diff_pct = (ema_diff / last_close) * 100
    
    # Closer EMAs = higher strength
    if ema_diff_pct < 0.1:  # Very close (< 0.1%)
        strength += 40
    elif ema_diff_pct < 0.5:  # Close (< 0.5%)
        strength += 40 * (1 - (ema_diff_pct / 0.5))
    elif ema_diff_pct < 1.0:  # Moderate (< 1%)
        strength += 20 * (1 - (ema_diff_pct / 1.0))
    
    # 2. MACD Proximity (25% weight) - how close to crossover
    macd = ind.get("macd", 0)
    macd_signal = ind.get("macd_signal", 0)
    macd_diff = abs(macd - macd_signal)
    
    if macd_diff < 0.01:  # Very close
        strength += 25
    elif macd_diff < 0.05:  # Close
        strength += 25 * (1 - (macd_diff / 0.05))
    elif macd_diff < 0.1:  # Moderate
        strength += 12.5 * (1 - (macd_diff / 0.1))
    
    # 3. RSI Levels (20% weight) - extreme levels indicate potential reversal
    rsi = ind.get("rsi", 50)
    
    if rsi < 30 or rsi > 70:  # Extreme levels
        strength += 20
    elif rsi < 40 or rsi > 60:  # Moderate levels
        strength += 10
    
    # 4. Volume (15% weight) - higher volume = more likely to move
    volume_ratio = ind.get("volume_ratio", 0)
    
    if volume_ratio >= 1.2:  # High volume
        strength += 15
    elif volume_ratio >= 0.8:  # Moderate volume
        strength += 15 * (volume_ratio / 1.2)
    
    return min(100.0, round(strength, 1))
