"""
Bollinger Squeeze Breakout Strategy
=====================================
Catches explosive breakout moves that follow periods of compressed volatility.

Concept:
  When a market consolidates, Bollinger Bands contract (squeeze).  Once the market
  resolves the squeeze, it tends to move strongly and rapidly in the breakout direction.
  Volume surging above average confirms that real buying / selling pressure is behind
  the move, not just noise.

Indicators:
  - Bollinger Bands (20, 2.0) — squeeze detection via band-width compression
  - Band-width history (last 15 bars) — squeeze = current width < 80 % of average
  - Volume (1.5× 20-period MA required) — confirms breakout is backed by flow
  - EMA 9 / 21 — direction of the breakout
  - MACD (12, 26, 9) histogram — momentum confirmation
  - RSI 14 — sanity check (avoids entering when RSI is at extreme opposite)

Signal:
  LONG  — squeeze was active in last 10 bars AND price ≥ upper BB AND EMA 9 > EMA 21
            AND MACD histogram > 0 AND volume ≥ 1.5× MA
  SHORT — squeeze was active in last 10 bars AND price ≤ lower BB AND EMA 9 < EMA 21
            AND MACD histogram < 0 AND volume ≥ 1.5× MA

TP : 15 % price move  (at 5x leverage → ≈ 75 % account gain)
SL : 10 % price move  (at 5x leverage → ≈ 50 % account loss)
Confidence threshold : 80 %
"""

import logging
from typing import Dict, List, Union
from strategy_base import TradingStrategy

logger = logging.getLogger(__name__)


class BreakoutVolStrategy(TradingStrategy):
    """
    Bollinger Squeeze Breakout with volume confirmation.
    Squeeze → Breakout → Volume surge = high-conviction momentum trade.
    Complementary to Bollinger RSI (which fades extremes); this strategy RIDES them.
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
        "cooldown_minutes":   0,

        # ── Bollinger Bands ───────────────────────────────────────────
        "bb_period":          20,
        "bb_std":             2.0,
        "squeeze_lookback":   15,            # Bars of width history for squeeze calc
        "squeeze_threshold":  0.80,          # Squeeze if width < 80 % of avg width
        "squeeze_window":     10,            # Check if any of last N bars were squeezed

        # ── EMA ───────────────────────────────────────────────────────
        "ema_fast":           9,
        "ema_slow":           21,
        "ema_trend":          50,

        # ── RSI ───────────────────────────────────────────────────────
        "rsi_period":         14,
        "rsi_extreme_long":   75,            # Don't LONG if RSI already overbought
        "rsi_extreme_short":  25,            # Don't SHORT if RSI already oversold

        # ── MACD ──────────────────────────────────────────────────────
        "macd_fast":          12,
        "macd_slow":          26,
        "macd_signal":        9,

        # ── ATR ───────────────────────────────────────────────────────
        "atr_period":         14,

        # ── Volume ────────────────────────────────────────────────────
        "volume_ma_period":   20,
        "min_volume_ratio":   1.5,           # Breakout needs strong volume surge

        # ── Position sizing ───────────────────────────────────────────
        "volatility_adjusted": True,
        "min_position_size":  0.0005,
        "max_position_size":  0.01,
    }

    # ──────────────────────────────────────────────────────────────────
    def get_name(self) -> str:
        return "Breakout Vol"

    def get_description(self) -> str:
        return (
            "Bollinger Squeeze Breakout with volume confirmation. "
            "Detects volatility compression (BB squeeze), then waits for price to break "
            "above/below the bands with ≥ 1.5× volume surge. "
            "EMA direction + MACD histogram confirmation. "
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

    def _rsi(self, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [d if d > 0 else 0.0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
        ag = sum(gains) / period
        al = sum(losses) / period
        return 50.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)

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

    def _macd(self, closes: list) -> dict:
        fp = self.CONFIG["macd_fast"]
        sp = self.CONFIG["macd_slow"]
        sg = self.CONFIG["macd_signal"]
        if len(closes) < sp + sg:
            return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}
        ef = self._ema(closes, fp)
        es = self._ema(closes, sp)
        ml = [ef[i] - es[i] for i in range(len(es))]
        sl = self._ema(ml, sg)
        if not sl:
            return {"macd": ml[-1] if ml else 0.0, "signal": 0.0, "histogram": 0.0}
        m, s = ml[-1], sl[-1]
        return {"macd": round(m, 8), "signal": round(s, 8), "histogram": round(m - s, 8)}

    def _bb_current(self, closes: list, period: int = 20,
                     std_mult: float = 2.0) -> dict:
        if len(closes) < period:
            return {"upper": None, "middle": None, "lower": None,
                    "width": None, "pct_b": None}
        window = closes[-period:]
        mid    = sum(window) / period
        if mid == 0:
            return {"upper": None, "middle": None, "lower": None,
                    "width": None, "pct_b": None}
        var   = sum((x - mid) ** 2 for x in window) / period
        std   = var ** 0.5
        upper = mid + std_mult * std
        lower = mid - std_mult * std
        price = closes[-1]
        width = (upper - lower) / mid
        pct_b = ((price - lower) / (upper - lower)
                 if (upper - lower) > 0 else 0.5)
        return {
            "upper":  round(upper, 6),
            "middle": round(mid,   6),
            "lower":  round(lower, 6),
            "width":  round(width, 6),
            "pct_b":  round(pct_b, 4),
        }

    def _bb_width_history(self, closes: list, period: int = 20,
                           std_mult: float = 2.0, lookback: int = 15) -> list:
        """
        Calculates BB width for each of the last `lookback` bars.
        Returns a list of widths (oldest → newest).
        """
        widths = []
        needed = period + lookback
        if len(closes) < needed:
            return widths
        for offset in range(lookback, 0, -1):
            end    = len(closes) - offset + 1
            window = closes[end - period: end]
            if len(window) < period:
                continue
            mid = sum(window) / period
            if mid == 0:
                continue
            var = sum((x - mid) ** 2 for x in window) / period
            std = var ** 0.5
            widths.append((std_mult * 2 * std) / mid)
        return widths

    # ── Compute all indicators ──────────────────────────────────────────

    def compute_indicators(self, candles: list) -> dict:
        closes  = [c["close"]  for c in candles]
        volumes = [c["volume"] for c in candles]

        bb      = self._bb_current(closes, self.CONFIG["bb_period"],
                                    self.CONFIG["bb_std"])
        widths  = self._bb_width_history(closes, self.CONFIG["bb_period"],
                                          self.CONFIG["bb_std"],
                                          self.CONFIG["squeeze_lookback"])
        rsi     = self._rsi(closes, self.CONFIG["rsi_period"])
        atr     = self._atr(candles, self.CONFIG["atr_period"])
        macd    = self._macd(closes)
        ef_s    = self._ema(closes, self.CONFIG["ema_fast"])
        es_s    = self._ema(closes, self.CONFIG["ema_slow"])
        et_s    = self._ema(closes, self.CONFIG["ema_trend"])

        # Squeeze analysis
        avg_width = sum(widths) / len(widths) if widths else 0
        squeeze_level = avg_width * self.CONFIG["squeeze_threshold"]
        sw = self.CONFIG["squeeze_window"]
        recent_widths = widths[-sw:] if len(widths) >= sw else widths
        was_squeezed  = (avg_width > 0
                         and any(w < squeeze_level for w in recent_widths))
        # Squeeze intensity: how much below average was the minimum recent width
        squeeze_intensity = 0.0
        if was_squeezed and avg_width > 0 and recent_widths:
            min_w = min(recent_widths)
            squeeze_intensity = max(0.0, 1.0 - min_w / avg_width)

        vm = self.CONFIG["volume_ma_period"]
        vol_ma    = (sum(volumes[-vm:]) / vm
                     if len(volumes) >= vm
                     else (sum(volumes) / len(volumes) if volumes else 0))
        vol_ratio = (volumes[-1] / vol_ma) if vol_ma > 0 else 0

        return {
            "bb_upper":          bb["upper"],
            "bb_middle":         bb["middle"],
            "bb_lower":          bb["lower"],
            "bb_width":          bb["width"],
            "bb_pct_b":          bb["pct_b"],
            "avg_bb_width":      round(avg_width, 6),
            "was_squeezed":      was_squeezed,
            "squeeze_intensity": round(squeeze_intensity, 4),
            "rsi":               rsi,
            "atr":               atr,
            "macd":              macd["macd"],
            "macd_signal":       macd["signal"],
            "macd_histogram":    macd["histogram"],
            "ema_fast":          ef_s[-1]  if ef_s             else None,
            "ema_fast_prev":     ef_s[-2]  if len(ef_s) >= 2   else None,
            "ema_slow":          es_s[-1]  if es_s             else None,
            "ema_slow_prev":     es_s[-2]  if len(es_s) >= 2   else None,
            "ema_trend":         et_s[-1]  if et_s             else None,
            "volume_ratio":      round(vol_ratio, 4),
            "last_close":        closes[-1]  if closes          else None,
        }

    # ── Confidence scoring ──────────────────────────────────────────────

    def calculate_confidence(self, ind: dict, position_type: str) -> float:
        """
        Max ≈ 105 pts → capped at 100:
          Volume surge (breakout strength)   35 pts
          BB breakout position               25 pts
          EMA alignment (fast/slow + trend)  20 pts
          MACD histogram                     15 pts
          Squeeze quality bonus               5 pts  (squeeze_intensity)
        """
        conf = 0.0

        vr      = ind.get("volume_ratio", 0)
        pct_b   = ind.get("bb_pct_b",    0.5)
        ef      = ind.get("ema_fast")
        es      = ind.get("ema_slow")
        et      = ind.get("ema_trend")
        efp     = ind.get("ema_fast_prev")
        esp     = ind.get("ema_slow_prev")
        price   = ind.get("last_close",  0)
        hist    = ind.get("macd_histogram", 0)
        macd    = ind.get("macd", 0)
        sig     = ind.get("macd_signal", 0)
        sq_int  = ind.get("squeeze_intensity", 0)

        # 1. Volume surge (35 pts) — breakout must be confirmed by volume
        min_vol = max(self.CONFIG["min_volume_ratio"], 0.01)
        if vr >= 2.5:
            conf += 35
        elif vr >= 2.0:
            conf += 30 + 5 * ((vr - 2.0) / 0.5)
        elif vr >= min_vol:
            conf += 30 * ((vr - min_vol) / (2.0 - min_vol))
        elif vr >= 1.0:
            conf += 10 * (vr / 1.0)

        # 2. BB breakout position (25 pts) — how far beyond the band
        if position_type == "LONG":
            if pct_b > 1.0:
                conf += 25
            elif pct_b >= 0.90:
                conf += 25 * ((pct_b - 0.90) / 0.10)
            elif pct_b >= 0.75:
                conf += 10 * ((pct_b - 0.75) / 0.15)
        else:
            if pct_b < 0.0:
                conf += 25
            elif pct_b <= 0.10:
                conf += 25 * ((0.10 - pct_b) / 0.10)
            elif pct_b <= 0.25:
                conf += 10 * ((0.25 - pct_b) / 0.15)

        # 3. EMA alignment (20 pts)
        if ef and es and price:
            if position_type == "LONG":
                if ef > es:
                    conf += 10
                    if efp and esp and efp <= esp:   # fresh EMA cross-up bonus
                        conf += 2
                if et and price > et:
                    conf += 10
                elif et and price > et * 0.99:
                    conf += 5
            else:
                if ef < es:
                    conf += 10
                    if efp and esp and efp >= esp:
                        conf += 2
                if et and price < et:
                    conf += 10
                elif et and price < et * 1.01:
                    conf += 5

        # 4. MACD histogram (15 pts)
        if position_type == "LONG":
            if macd > sig and hist > 0:
                conf += 15
            elif macd > sig:
                conf += 8
            elif hist > 0:
                conf += 5
        else:
            if macd < sig and hist < 0:
                conf += 15
            elif macd < sig:
                conf += 8
            elif hist < 0:
                conf += 5

        # 5. Squeeze intensity bonus (5 pts)
        if ind.get("was_squeezed", False):
            conf += 5 * min(1.0, sq_int * 2)   # ramps from 0 → 5 as intensity grows

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
        min_c = (max(self.CONFIG["ema_trend"], self.CONFIG["macd_slow"])
                 + self.CONFIG["bb_period"]
                 + self.CONFIG["squeeze_lookback"] + 5)
        if len(candles) < min_c:
            return _null if return_confidence else None

        ind = self.compute_indicators(candles)
        if ind.get("bb_upper") is None or ind.get("ema_fast") is None:
            return _null if return_confidence else None

        price     = ind["last_close"]
        bb_up     = ind["bb_upper"]
        bb_low    = ind["bb_lower"]
        pct_b     = ind["bb_pct_b"]
        ef, es    = ind["ema_fast"], ind["ema_slow"]
        hist      = ind["macd_histogram"]
        vol_ok    = ind["volume_ratio"] >= self.CONFIG["min_volume_ratio"]
        squeezed  = ind.get("was_squeezed", False)
        atr       = ind["atr"]
        rsi       = ind["rsi"]

        # RSI sanity guards — don't LONG if RSI already very overbought, etc.
        rsi_ok_long  = rsi < self.CONFIG["rsi_extreme_long"]
        rsi_ok_short = rsi > self.CONFIG["rsi_extreme_short"]

        signal = None

        # ── LONG: squeeze → price breaks above upper BB + volume + EMA up + MACD bullish ──
        if (squeezed
                and pct_b >= 0.90              # price at / above upper band
                and price >= bb_up * 0.998
                and ef > es                    # short-term uptrend
                and hist > 0                   # MACD histogram confirms momentum
                and vol_ok
                and rsi_ok_long):
            signal = "LONG"

        # ── SHORT: squeeze → price breaks below lower BB + volume + EMA down + MACD bearish ──
        elif (squeezed
              and pct_b <= 0.10
              and price <= bb_low * 1.002
              and ef < es
              and hist < 0
              and vol_ok
              and rsi_ok_short):
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
                f"[Breakout Vol] {signal} | "
                f"pct_b:{pct_b:.2f} BB:{bb_low:.4f}-{bb_up:.4f} "
                f"Squeeze:{squeezed}(intensity:{ind.get('squeeze_intensity', 0):.2f}) "
                f"Vol:{ind['volume_ratio']:.2f}x "
                f"EMA:{ef:.4f}/{es:.4f} MACD_hist:{hist:.6f} RSI:{rsi} "
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
