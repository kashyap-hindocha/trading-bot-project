"""
Bollinger Bands + RSI Momentum Strategy
========================================
Counter-trend momentum strategy: buy deeply-oversold dips, short deeply-overbought spikes.

Concept:
  In any trend, price periodically stretches to an extreme relative to its recent average.
  When price touches / crosses the outer Bollinger Band AND the RSI confirms the extreme,
  and the RSI begins to reverse (momentum shift), there is a high-probability bounce.

Indicators:
  - Bollinger Bands (20, 2.0) — identifies price extremes relative to the 20-SMA
  - RSI 14 — confirms oversold (< 35) / overbought (> 65) zones
  - RSI series momentum — checks that RSI is turning AWAY from the extreme (V-bottom / inverted-V)
  - EMA 9 / 21 — short-term trend alignment
  - EMA 50 — major trend filter (relaxed: price within 2 % of EMA50 is acceptable)
  - Volume confirmation (≥ 80 % of 20-period MA)

Signal:
  LONG  — RSI < 35, RSI turning up (RSI[i] > RSI[i-1]), pct_b ≤ 0.25, volume OK
  SHORT — RSI > 65, RSI turning down (RSI[i] < RSI[i-1]), pct_b ≥ 0.75, volume OK

TP : 15 % price move  (at 5x leverage → ≈ 75 % account gain)
SL : 10 % price move  (at 5x leverage → ≈ 50 % account loss)
Confidence threshold : 80 %
"""

import logging
from typing import Dict, List, Union
from strategy_base import TradingStrategy

logger = logging.getLogger(__name__)


class BollingerRSIMomentum(TradingStrategy):
    """
    Mean-reversion momentum strategy.
    Buys oversold dips at lower Bollinger Band; shorts overbought spikes at upper band.
    RSI momentum shift (turning from extreme) reduces whipsaw entries.
    """

    CONFIG = {
        "pair":               "B-BTC_USDT",
        "interval":           "5m",
        "leverage":           5,
        "quantity":           0.001,
        "inr_amount":         300.0,
        "tp_pct":             0.15,          # ── TP: 15 % price move ──
        "sl_pct":             0.10,          # ── SL: 10 % price move ──
        "max_open_trades":    3,
        "auto_execute":       True,
        "confidence_threshold": 80.0,

        # ── Bollinger Bands ───────────────────────────────────────────
        "bb_period":          20,
        "bb_std":             2.0,

        # ── RSI ───────────────────────────────────────────────────────
        "rsi_period":         14,
        "rsi_oversold":       35,            # Conservative — avoids early entries
        "rsi_overbought":     65,

        # ── EMA ───────────────────────────────────────────────────────
        "ema_fast":           9,
        "ema_slow":           21,
        "ema_trend":          50,

        # ── ATR ───────────────────────────────────────────────────────
        "atr_period":         14,

        # ── Volume ────────────────────────────────────────────────────
        "volume_ma_period":   20,
        "min_volume_ratio":   0.8,

        # ── Position sizing ───────────────────────────────────────────
        "volatility_adjusted": True,
        "min_position_size":  0.0005,
        "max_position_size":  0.01,
    }

    # ──────────────────────────────────────────────────────────────────
    def get_name(self) -> str:
        return "Bollinger RSI"

    def get_description(self) -> str:
        return (
            "Bollinger Bands + RSI Momentum. "
            "Buys oversold dips at lower BB; shorts overbought spikes at upper BB. "
            "RSI momentum shift (V-bottom / inverted-V) reduces whipsaws. "
            "TP 15 % | SL 10 % | Confidence ≥ 80 %."
        )

    # ── Pure-Python indicator helpers ───────────────────────────────────

    def _ema(self, values: list, period: int) -> list:
        if len(values) < period:
            return []
        k = 2 / (period + 1)
        out = [sum(values[:period]) / period]
        for v in values[period:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    def _rsi_series(self, closes: list, period: int = 14) -> list:
        """
        Returns [rsi_2_bars_ago, rsi_prev, rsi_current].
        Used to detect RSI momentum shift (turning from extreme).
        """
        if len(closes) < period + 3:
            return [50.0, 50.0, 50.0]
        results = []
        for offset in range(2, -1, -1):
            end    = len(closes) - offset
            window = closes[max(0, end - period - 1): end]
            if len(window) < period + 1:
                results.append(50.0)
                continue
            deltas = [window[i] - window[i - 1] for i in range(1, len(window))]
            gains  = [d if d > 0 else 0.0 for d in deltas[-period:]]
            losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
            ag = sum(gains) / period
            al = sum(losses) / period
            results.append(100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2))
        return results   # [rsi_2_bars_ago, rsi_1_bar_ago, rsi_now]

    def _atr(self, candles: list, period: int = 14) -> float:
        if len(candles) < period:
            return 0.0
        tr = []
        for i, c in enumerate(candles):
            pc = candles[i - 1]["close"] if i > 0 else c["close"]
            tr.append(max(c["high"] - c["low"],
                          abs(c["high"] - pc),
                          abs(c["low"]  - pc)))
        return round(sum(tr[-period:]) / period, 6)

    def _bollinger_bands(self, closes: list,
                          period: int = 20, std_mult: float = 2.0) -> dict:
        if len(closes) < period:
            return {"upper": None, "middle": None, "lower": None,
                    "width": None, "pct_b": None}
        window   = closes[-period:]
        mid      = sum(window) / period
        variance = sum((x - mid) ** 2 for x in window) / period
        std      = variance ** 0.5
        upper    = mid + std_mult * std
        lower    = mid - std_mult * std
        price    = closes[-1]
        width    = (upper - lower) / mid if mid > 0 else 0
        pct_b    = ((price - lower) / (upper - lower)
                    if (upper - lower) > 0 else 0.5)
        return {
            "upper":  round(upper, 6),
            "middle": round(mid,   6),
            "lower":  round(lower, 6),
            "width":  round(width, 6),
            "pct_b":  round(pct_b, 4),
        }

    # ── Compute all indicators ──────────────────────────────────────────

    def compute_indicators(self, candles: list) -> dict:
        closes  = [c["close"]  for c in candles]
        volumes = [c["volume"] for c in candles]

        bb      = self._bollinger_bands(closes, self.CONFIG["bb_period"],
                                        self.CONFIG["bb_std"])
        rsi_seq = self._rsi_series(closes, self.CONFIG["rsi_period"])
        atr     = self._atr(candles, self.CONFIG["atr_period"])
        ef_s    = self._ema(closes, self.CONFIG["ema_fast"])
        es_s    = self._ema(closes, self.CONFIG["ema_slow"])
        et_s    = self._ema(closes, self.CONFIG["ema_trend"])

        vm = self.CONFIG["volume_ma_period"]
        vol_ma    = (sum(volumes[-vm:]) / vm
                     if len(volumes) >= vm
                     else (sum(volumes) / len(volumes) if volumes else 0))
        vol_ratio = (volumes[-1] / vol_ma) if vol_ma > 0 else 0

        return {
            "bb_upper":     bb["upper"],
            "bb_middle":    bb["middle"],
            "bb_lower":     bb["lower"],
            "bb_width":     bb["width"],
            "bb_pct_b":     bb["pct_b"],   # 0 = at lower band, 1 = at upper band
            "rsi":          rsi_seq[2],     # current RSI
            "rsi_prev":     rsi_seq[1],     # RSI 1 bar ago
            "rsi_prev2":    rsi_seq[0],     # RSI 2 bars ago
            "atr":          atr,
            "ema_fast":     ef_s[-1]  if ef_s             else None,
            "ema_slow":     es_s[-1]  if es_s             else None,
            "ema_trend":    et_s[-1]  if et_s             else None,
            "volume_ratio": round(vol_ratio, 4),
            "last_close":   closes[-1]      if closes       else None,
        }

    # ── Confidence scoring ──────────────────────────────────────────────

    def calculate_confidence(self, ind: dict, position_type: str) -> float:
        """
        Max ≈ 105 pts → capped at 100:
          BB price extreme (pct_b)           30 pts
          RSI extreme + momentum shift       30 pts  (20 extreme + 10 shift)
          EMA trend alignment                20 pts  (10 EMA 9/21 + 10 EMA 50)
          Volume                             15 pts
          RSI depth bonus                     5 pts  (RSI far into extreme zone)
        """
        conf = 0.0

        pct_b  = ind.get("bb_pct_b",    0.5)
        rsi    = ind.get("rsi",         50)
        rsi_p  = ind.get("rsi_prev",    50)
        rsi_p2 = ind.get("rsi_prev2",   50)
        ef     = ind.get("ema_fast")
        es     = ind.get("ema_slow")
        et     = ind.get("ema_trend")
        price  = ind.get("last_close",  0)
        vr     = ind.get("volume_ratio", 0)
        os_    = self.CONFIG["rsi_oversold"]
        ob_    = self.CONFIG["rsi_overbought"]

        # 1. BB price extreme (30 pts)
        if position_type == "LONG":
            if pct_b <= 0.0:
                conf += 30
            elif pct_b <= 0.15:
                conf += 30 * (1 - pct_b / 0.15)
            elif pct_b <= 0.30:
                conf += 10 * (1 - (pct_b - 0.15) / 0.15)
        else:
            if pct_b >= 1.0:
                conf += 30
            elif pct_b >= 0.85:
                conf += 30 * ((pct_b - 0.85) / 0.15)
            elif pct_b >= 0.70:
                conf += 10 * ((pct_b - 0.70) / 0.15)

        # 2. RSI extreme + momentum shift (30 pts)
        # Confirmed V-turn: RSI was falling, last bar lower, now rising
        rsi_turn_up   = rsi > rsi_p                       # RSI rising
        rsi_turn_down = rsi < rsi_p                       # RSI falling
        v_bottom      = rsi > rsi_p and rsi_p <= rsi_p2   # V-bottom shape
        inv_v_top     = rsi < rsi_p and rsi_p >= rsi_p2   # inverted-V shape

        if position_type == "LONG":
            if rsi < os_:
                conf += 20
                if v_bottom:
                    conf += 10
                elif rsi_turn_up:
                    conf += 5
            elif rsi < os_ + 10:
                conf += 10 * (1 - (rsi - os_) / 10)
                if rsi_turn_up:
                    conf += 5
        else:
            if rsi > ob_:
                conf += 20
                if inv_v_top:
                    conf += 10
                elif rsi_turn_down:
                    conf += 5
            elif rsi > ob_ - 10:
                conf += 10 * (1 - (ob_ - rsi) / 10)
                if rsi_turn_down:
                    conf += 5

        # 3. EMA alignment (20 pts)
        if ef and es and price:
            if position_type == "LONG":
                if ef > es:
                    conf += 10
                if et and price > et:
                    conf += 10
                elif et and price > et * 0.98:   # within 2 % below EMA50 is OK
                    conf += 5
            else:
                if ef < es:
                    conf += 10
                if et and price < et:
                    conf += 10
                elif et and price < et * 1.02:
                    conf += 5

        # 4. Volume (15 pts)
        min_vol = max(self.CONFIG["min_volume_ratio"], 0.01)
        if vr >= 1.0:
            conf += 15
        elif vr >= min_vol:
            conf += 15 * (vr / min_vol)

        # 5. RSI depth bonus (5 pts)
        if position_type == "LONG" and rsi < os_ - 5:
            conf += 5
        elif position_type == "SHORT" and rsi > ob_ + 5:
            conf += 5

        return min(100.0, round(conf, 1))

    # ── Position sizing ─────────────────────────────────────────────────

    def calculate_position_size(self, entry_price: float, atr: float,
                                 rsi: float, position_type: str) -> float:
        base = self.CONFIG["quantity"]
        if not self.CONFIG["volatility_adjusted"] or not entry_price or not atr:
            return base
        vol_pct = (atr / entry_price) * 100
        if vol_pct < 0.5:
            m = 1.0
        elif vol_pct > 3.0:
            m = 0.5
        else:
            m = 1.0 - ((vol_pct - 0.5) / 2.5) * 0.5
        return round(max(self.CONFIG["min_position_size"],
                         min(self.CONFIG["max_position_size"], base * m)), 6)

    # ── Main evaluate ────────────────────────────────────────────────────

    def evaluate(self, candles: List[Dict], return_confidence: bool = True) -> Union[str, None, Dict]:
        _null = {
            "signal": None, "confidence": 0.0, "auto_execute": False,
            "atr": 0.0, "position_size": 0.0, "trailing_stop": 0.0,
        }
        min_c = max(self.CONFIG["ema_trend"], self.CONFIG["bb_period"]) + 5
        if len(candles) < min_c:
            return _null if return_confidence else None

        ind = self.compute_indicators(candles)
        if ind.get("bb_upper") is None or ind.get("ema_fast") is None:
            return _null if return_confidence else None

        rsi    = ind["rsi"]
        rsi_p  = ind["rsi_prev"]
        pct_b  = ind["bb_pct_b"]
        atr    = ind["atr"]
        price  = ind["last_close"]
        vol_ok = ind["volume_ratio"] >= self.CONFIG["min_volume_ratio"]
        os_    = self.CONFIG["rsi_oversold"]
        ob_    = self.CONFIG["rsi_overbought"]

        # RSI momentum direction
        rsi_turning_up   = rsi > rsi_p
        rsi_turning_down = rsi < rsi_p

        signal = None

        # ── LONG: oversold RSI + price at lower BB + RSI turning up + volume ──
        if (rsi < os_
                and rsi_turning_up
                and pct_b <= 0.25
                and vol_ok):
            signal = "LONG"

        # ── SHORT: overbought RSI + price at upper BB + RSI turning down + volume ──
        elif (rsi > ob_
              and rsi_turning_down
              and pct_b >= 0.75
              and vol_ok):
            signal = "SHORT"

        confidence   = 0.0
        auto_execute = False
        pos_size     = 0.0
        trailing_stop = 0.0

        if signal:
            confidence   = self.calculate_confidence(ind, signal)
            auto_execute = (self.CONFIG["auto_execute"]
                            and confidence >= self.CONFIG["confidence_threshold"])
            pos_size     = self.calculate_position_size(price, atr, rsi, signal)
            trailing_stop = (round(price - atr * 2.0, 6) if signal == "LONG"
                             else round(price + atr * 2.0, 6))
            logger.info(
                f"[Bollinger RSI] {signal} | "
                f"pct_b:{pct_b:.2f} RSI:{rsi}(prev:{rsi_p}) "
                f"EMA:{ind.get('ema_fast', 0):.4f}/{ind.get('ema_slow', 0):.4f} "
                f"Vol:{ind['volume_ratio']:.2f}x "
                f"Conf:{confidence:.1f}% AE:{auto_execute}"
            )

        if return_confidence:
            return {
                "signal": signal, "confidence": confidence,
                "auto_execute": auto_execute, "atr": atr,
                "position_size": pos_size, "trailing_stop": trailing_stop,
            }
        return signal

    # ── TP / SL ──────────────────────────────────────────────────────────

    def calculate_tp_sl(self, entry_price: float, position_type: str,
                         atr: float = 0.0) -> tuple:
        """
        Fixed-percentage TP/SL applied to the raw price.
          TP = 15 % → price must move 15 % from entry
          SL = 10 % → price must move 10 % against entry
        At 5x leverage that translates to ≈75 % account gain / ≈50 % account loss.
        """
        tp = self.CONFIG["tp_pct"]   # 0.15
        sl = self.CONFIG["sl_pct"]   # 0.10
        if position_type == "LONG":
            return round(entry_price * (1 + tp), 4), round(entry_price * (1 - sl), 4)
        return round(entry_price * (1 - tp), 4), round(entry_price * (1 + sl), 4)
