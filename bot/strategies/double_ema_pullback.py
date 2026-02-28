"""
Double EMA Pullback - Buy Sell Signal
Converted from Pine Script (strict conversion, no extra logic).

Pine logic:
  ema1 = ta.ema(close, 50)
  ema2 = ta.ema(close, 200)
  buySignal  = ta.crossover(close, ema1) and ema1 > ema2 and close[pbStep] > ema1
  sellSignal = ta.crossunder(close, ema1) and ema1 < ema2 and close[pbStep] < ema1
  pbStep = 5 (Backstep of Pullback)
"""

import logging
from typing import Dict, List, Union
from strategy_base import TradingStrategy

logger = logging.getLogger(__name__)


class DoubleEMAPullback(TradingStrategy):
    CONFIG = {
        "pair":               "B-BTC_USDT",
        "interval":           "5m",
        "leverage":           5,
        "quantity":           0.001,
        "inr_amount":         300.0,
        "tp_pct":             0.015,
        "sl_pct":             0.008,
        "max_open_trades":    1,
        "auto_execute":       True,
        "confidence_threshold": 80.0,
        "cooldown_minutes":   0,
        "pb_step":            5,
        "ema1_period":        50,
        "ema2_period":        200,
    }

    def get_name(self) -> str:
        return "Double EMA Pullback"

    def get_description(self) -> str:
        return "Double EMA Pullback - Buy Sell Signal. Crossover(close, EMA50) with EMA50 > EMA200 and pullback condition; crossunder for sell."

    def _ema(self, values: list, period: int) -> list:
        if len(values) < period:
            return []
        k = 2 / (period + 1)
        out = [sum(values[:period]) / period]
        for v in values[period:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    def evaluate(self, candles: List[Dict], return_confidence: bool = True) -> Union[str, None, Dict]:
        _null = {
            "signal": None, "confidence": 0.0, "auto_execute": False,
            "atr": 0.0, "position_size": 0.0, "trailing_stop": 0.0,
        }
        cfg = self.CONFIG
        pb_step = cfg["pb_step"]
        ema1_period = cfg["ema1_period"]
        ema2_period = cfg["ema2_period"]
        need = max(ema2_period + pb_step + 2, 200 + pb_step + 2)
        if len(candles) < need:
            return _null if return_confidence else None

        closes = [float(c.get("close", c.get("c", 0))) for c in candles]
        ema1 = self._ema(closes, ema1_period)
        ema2 = self._ema(closes, ema2_period)
        if len(ema1) < 2 + pb_step or len(ema2) < 2 + pb_step:
            return _null if return_confidence else None

        close_curr = closes[-1]
        close_prev = closes[-2]
        ema1_curr = ema1[-1]
        ema1_prev = ema1[-2]
        ema2_curr = ema2[-1]
        close_pb = closes[-1 - pb_step]

        crossover_close_ema1 = close_prev <= ema1_prev and close_curr > ema1_curr
        crossunder_close_ema1 = close_prev >= ema1_prev and close_curr < ema1_curr

        buy_signal = crossover_close_ema1 and ema1_curr > ema2_curr and close_pb > ema1_curr
        sell_signal = crossunder_close_ema1 and ema1_curr < ema2_curr and close_pb < ema1_curr

        signal = None
        if buy_signal:
            signal = "LONG"
        elif sell_signal:
            signal = "SHORT"

        # When no signal: expose a 0–100 "readiness" so dashboard shows meaningful % (proximity to EMAs)
        if signal:
            confidence = 100.0
        else:
            # Readiness: how far price is from EMA1 as % of EMA1, mapped to 0–99 (never 100 without signal)
            if ema1_curr and ema1_curr > 0:
                pct_from_ema1 = (close_curr - ema1_curr) / ema1_curr * 100  # e.g. +0.5% above, -0.3% below
                # Map to 0–99: above EMA1 -> 50–99, below -> 0–50
                readiness = 50.0 + max(-50, min(49, pct_from_ema1 * 25))  # scale so ~±2% = full range
                confidence = max(0.0, min(99.0, readiness))
            else:
                confidence = 0.0
        if return_confidence:
            return {
                "signal": signal,
                "confidence": confidence,
                "auto_execute": confidence >= cfg["confidence_threshold"],
                "atr": 0.0,
                "position_size": cfg["quantity"],
                "trailing_stop": 0.0,
            }
        return signal

    def calculate_tp_sl(self, entry_price: float, position_type: str, atr: float = 0.0, **kwargs) -> tuple:
        tp = self.CONFIG["tp_pct"]
        sl = self.CONFIG["sl_pct"]
        if position_type == "LONG":
            return round(entry_price * (1 + tp), 4), round(entry_price * (1 - sl), 4)
        return round(entry_price * (1 - tp), 4), round(entry_price * (1 + sl), 4)
