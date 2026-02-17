"""
Simple EMA Crossover Strategy
=============================
Basic strategy using only EMA crossover and RSI filter.
Good for beginners and testing.
"""

import logging
from typing import Dict, List, Optional, Union
from strategy_base import TradingStrategy

logger = logging.getLogger(__name__)


class SimpleEMAStrategy(TradingStrategy):
    """
    Simple EMA crossover strategy with basic RSI filter.
    """

    CONFIG = {
        "pair":          "B-BTC_USDT",
        "interval":      "5m",
        "leverage":      5,
        "quantity":      0.001,
        "inr_amount":    300.0,
        "tp_pct":        0.02,              # 2% take profit
        "sl_pct":        0.01,              # 1% stop loss
        "max_open_trades": 3,               # More conservative
        "auto_execute":  True,
        "confidence_threshold": 80.0,       # Higher threshold

        # Simple indicators
        "ema_fast":      9,
        "ema_slow":      21,
        "rsi_period":    14,
        "rsi_overbought": 70,
        "rsi_oversold":   30,
    }

    def get_name(self) -> str:
        return "Simple EMA"

    def get_description(self) -> str:
        return ("Basic EMA crossover strategy with RSI filter. "
                "Conservative settings for beginners.")

    def _ema(self, values: list[float], period: int) -> list[float]:
        """Calculate Exponential Moving Average"""
        if len(values) < period:
            return []
        k = 2 / (period + 1)
        ema = [sum(values[:period]) / period]
        for v in values[period:]:
            ema.append(v * k + ema[-1] * (1 - k))
        return ema

    def _rsi(self, closes: list[float], period: int = 14) -> float:
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

    def compute_indicators(self, candles: list[dict]) -> dict:
        """Compute basic indicators: EMA and RSI"""
        closes = [c["close"] for c in candles]

        ema_fast_series = self._ema(closes, self.CONFIG["ema_fast"])
        ema_slow_series = self._ema(closes, self.CONFIG["ema_slow"])
        rsi = self._rsi(closes, self.CONFIG["rsi_period"])

        return {
            "ema_fast": ema_fast_series[-1] if ema_fast_series else None,
            "ema_slow": ema_slow_series[-1] if ema_slow_series else None,
            "ema_fast_prev": ema_fast_series[-2] if len(ema_fast_series) >= 2 else None,
            "ema_slow_prev": ema_slow_series[-2] if len(ema_slow_series) >= 2 else None,
            "rsi": rsi,
            "last_close": closes[-1] if closes else None,
        }

    def calculate_confidence(self, ind: dict, position_type: str) -> float:
        """Simple confidence calculation"""
        confidence = 0.0

        if not ind.get("ema_fast") or not ind.get("ema_slow"):
            return 0.0

        # EMA alignment (60% weight)
        if position_type == "LONG" and ind["ema_fast"] > ind["ema_slow"]:
            confidence += 60
            # Bonus for fresh crossover
            if (ind["ema_fast_prev"] and ind["ema_slow_prev"] and
                ind["ema_fast_prev"] <= ind["ema_slow_prev"]):
                confidence += 20
        elif position_type == "SHORT" and ind["ema_fast"] < ind["ema_slow"]:
            confidence += 60
            # Bonus for fresh crossover
            if (ind["ema_fast_prev"] and ind["ema_slow_prev"] and
                ind["ema_fast_prev"] >= ind["ema_slow_prev"]):
                confidence += 20

        # RSI alignment (40% weight)
        rsi = ind.get("rsi", 50)
        if position_type == "LONG":
            if rsi < self.CONFIG["rsi_oversold"]:
                confidence += 40
            elif rsi < self.CONFIG["rsi_overbought"]:
                confidence += 40 * (self.CONFIG["rsi_overbought"] - rsi) / self.CONFIG["rsi_overbought"]
        else:
            if rsi > self.CONFIG["rsi_overbought"]:
                confidence += 40
            elif rsi > self.CONFIG["rsi_oversold"]:
                confidence += 40 * (rsi - self.CONFIG["rsi_oversold"]) / (100 - self.CONFIG["rsi_oversold"])

        return min(100.0, round(confidence, 1))

    def evaluate(self, candles: List[Dict], return_confidence: bool = True) -> Union[str, None, Dict]:
        """
        Simple EMA crossover + RSI strategy
        """
        if len(candles) < self.CONFIG["ema_slow"] + 5:
            if return_confidence:
                return {"signal": None, "confidence": 0.0, "auto_execute": False}
            return None

        ind = self.compute_indicators(candles)

        if None in (ind["ema_fast"], ind["ema_slow"], ind["ema_fast_prev"], ind["ema_slow_prev"]):
            if return_confidence:
                return {"signal": None, "confidence": 0.0, "auto_execute": False}
            return None

        # EMA crossover detection
        crossed_up = (ind["ema_fast_prev"] <= ind["ema_slow_prev"] and
                      ind["ema_fast"] > ind["ema_slow"])
        crossed_down = (ind["ema_fast_prev"] >= ind["ema_slow_prev"] and
                        ind["ema_fast"] < ind["ema_slow"])

        signal = None
        confidence = 0.0
        auto_execute = False

        # LONG signal
        if crossed_up and ind["rsi"] < self.CONFIG["rsi_overbought"]:
            signal = "LONG"
            confidence = self.calculate_confidence(ind, "LONG")
            auto_execute = self.CONFIG["auto_execute"] and confidence >= self.CONFIG["confidence_threshold"]

        # SHORT signal
        elif crossed_down and ind["rsi"] > self.CONFIG["rsi_oversold"]:
            signal = "SHORT"
            confidence = self.calculate_confidence(ind, "SHORT")
            auto_execute = self.CONFIG["auto_execute"] and confidence >= self.CONFIG["confidence_threshold"]

        if return_confidence:
            return {
                "signal": signal,
                "confidence": confidence,
                "auto_execute": auto_execute
            }
        return signal

    def calculate_tp_sl(self, entry_price: float, position_type: str, **kwargs) -> tuple[float, float]:
        """Simple fixed TP/SL calculation"""
        tp_pct = self.CONFIG["tp_pct"]
        sl_pct = self.CONFIG["sl_pct"]

        if position_type == "LONG":
            tp = round(entry_price * (1 + tp_pct), 4)
            sl = round(entry_price * (1 - sl_pct), 4)
        else:
            tp = round(entry_price * (1 - tp_pct), 4)
            sl = round(entry_price * (1 + sl_pct), 4)

        return tp, sl