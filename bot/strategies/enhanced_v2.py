"""
Enhanced Strategy v2 — Supertrend + Triple EMA + MACD Trend Follower
=====================================================================
Professional trend-following strategy rebuilt with:
  - Supertrend (ATR-based dynamic trend line) as the PRIMARY signal
  - Triple EMA (9 / 21 / 50) for trend strength, crossover, and major-trend filter
  - MACD (12, 26, 9) momentum confirmation
  - Volume confirmation (≥ 80 % of 20-period MA)
  - Wilder-smoothed ATR for position sizing and trailing-stop reference

Signal logic:
  LONG  — Supertrend bullish AND EMA 9 > EMA 21 AND (ST just flipped OR EMA crossed up)
            AND MACD ≥ signal AND volume OK
  SHORT — Supertrend bearish AND EMA 9 < EMA 21 AND (ST just flipped OR EMA crossed down)
            AND MACD ≤ signal AND volume OK

TP : 15 % price move  (at 5x leverage → ≈ 75 % account gain)
SL : 10 % price move  (at 5x leverage → ≈ 50 % account loss)
Risk : Reward = 1 : 1.5
Confidence threshold : 80 %
"""

import logging
from typing import Dict, List, Union
from strategy_base import TradingStrategy

logger = logging.getLogger(__name__)


class EnhancedStrategyV2(TradingStrategy):
    """
    Supertrend + Triple EMA Trend Follower.
    Fires on every CLOSED candle via the WebSocket candlestick stream.
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
        "cooldown_minutes":   0,            # 0 = allow re-entry as soon as position closes; set >0 to wait before re-opening

        # ── EMA ───────────────────────────────────────────────────────
        "ema_fast":           9,
        "ema_slow":           21,
        "ema_trend":          50,            # Higher-timeframe trend filter

        # ── RSI ───────────────────────────────────────────────────────
        "rsi_period":         14,
        "rsi_overbought":     70,
        "rsi_oversold":       30,

        # ── ATR ───────────────────────────────────────────────────────
        "atr_period":         14,
        "atr_multiplier":     2.0,           # Trailing-stop reference only

        # ── Supertrend ────────────────────────────────────────────────
        "st_period":          10,
        "st_multiplier":      3.0,

        # ── MACD ──────────────────────────────────────────────────────
        "macd_fast":          12,
        "macd_slow":          26,
        "macd_signal":        9,

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
        return "Enhanced v2"

    def get_description(self) -> str:
        return (
            "Supertrend + Triple EMA (9/21/50) trend follower with MACD & volume confirmation. "
            "Supertrend (10, 3) as primary signal; EMA crossover + EMA50 filter for trend "
            "strength; MACD momentum; volume ≥ 80 %. "
            "TP 15 % | SL 10 % | Confidence ≥ 80 %."
        )

    # ── Pure-Python indicator helpers ──────────────────────────────────

    def _ema(self, values: list, period: int) -> list:
        """Exponential Moving Average."""
        if len(values) < period:
            return []
        k = 2 / (period + 1)
        out = [sum(values[:period]) / period]
        for v in values[period:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    def _rsi(self, closes: list, period: int = 14) -> float:
        """Wilder RSI."""
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [d if d > 0 else 0.0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
        ag = sum(gains) / period
        al = sum(losses) / period
        return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)

    def _atr(self, candles: list, period: int = 14) -> float:
        """Simple-average ATR (sufficient for position sizing)."""
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
        """Standard MACD."""
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

    def _supertrend(self, candles: list, period: int = 10, multiplier: float = 3.0) -> list:
        """
        Supertrend with Wilder-smoothed ATR.
        Returns list of {"value": float, "direction": int}
          direction = 1  → bullish (price above the line)
          direction = -1 → bearish (price below the line)
        """
        n = len(candles)
        if n < period + 1:
            return []

        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        closes = [c["close"] for c in candles]

        # Wilder's smoothed ATR
        tr = []
        for i in range(n):
            pc = closes[i - 1] if i > 0 else closes[0]
            tr.append(max(highs[i] - lows[i],
                          abs(highs[i] - pc),
                          abs(lows[i]  - pc)))
        atr = [0.0] * n
        atr[period - 1] = sum(tr[:period]) / period
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        fu = [0.0] * n   # final upper band
        fl = [0.0] * n   # final lower band
        st = [0.0] * n   # supertrend value
        di = [1]   * n   # direction: 1=bull, -1=bear

        for i in range(period - 1, n):
            hl2 = (highs[i] + lows[i]) / 2.0
            bu  = hl2 + multiplier * atr[i]
            bl  = hl2 - multiplier * atr[i]

            if i == period - 1:
                fu[i], fl[i], di[i], st[i] = bu, bl, 1, bl
                continue

            # Band adjustment (prevents band from widening when price is trending)
            fu[i] = bu if (bu < fu[i-1] or closes[i-1] > fu[i-1]) else fu[i-1]
            fl[i] = bl if (bl > fl[i-1] or closes[i-1] < fl[i-1]) else fl[i-1]

            # Direction flip logic
            if st[i - 1] == fu[i - 1]:        # was bearish
                di[i] = 1  if closes[i] > fu[i] else -1
            else:                              # was bullish
                di[i] = -1 if closes[i] < fl[i] else 1

            st[i] = fl[i] if di[i] == 1 else fu[i]

        return [{"value": round(st[i], 6), "direction": di[i]} for i in range(n)]

    # ── Compute all indicators ──────────────────────────────────────────

    def compute_indicators(self, candles: list) -> dict:
        closes  = [c["close"]  for c in candles]
        volumes = [c["volume"] for c in candles]

        ef_s = self._ema(closes, self.CONFIG["ema_fast"])
        es_s = self._ema(closes, self.CONFIG["ema_slow"])
        et_s = self._ema(closes, self.CONFIG["ema_trend"])
        rsi  = self._rsi(closes, self.CONFIG["rsi_period"])
        atr  = self._atr(candles, self.CONFIG["atr_period"])
        macd = self._macd(closes)
        st   = self._supertrend(candles, self.CONFIG["st_period"], self.CONFIG["st_multiplier"])

        vm = self.CONFIG["volume_ma_period"]
        vol_ma    = (sum(volumes[-vm:]) / vm
                     if len(volumes) >= vm
                     else (sum(volumes) / len(volumes) if volumes else 0))
        vol_ratio = (volumes[-1] / vol_ma) if vol_ma > 0 else 0

        return {
            "ema_fast":       ef_s[-1]  if ef_s              else None,
            "ema_fast_prev":  ef_s[-2]  if len(ef_s) >= 2    else None,
            "ema_slow":       es_s[-1]  if es_s              else None,
            "ema_slow_prev":  es_s[-2]  if len(es_s) >= 2    else None,
            "ema_trend":      et_s[-1]  if et_s              else None,
            "rsi":            rsi,
            "atr":            atr,
            "macd":           macd["macd"],
            "macd_signal":    macd["signal"],
            "macd_histogram": macd["histogram"],
            "volume_ratio":   round(vol_ratio, 4),
            "last_close":     closes[-1]        if closes       else None,
            "st_direction":   st[-1]["direction"] if st           else 1,
            "st_prev_dir":    st[-2]["direction"] if len(st) >= 2 else 1,
            "st_value":       st[-1]["value"]     if st           else 0.0,
        }

    # ── Confidence scoring ──────────────────────────────────────────────

    def calculate_confidence(self, ind: dict, position_type: str) -> float:
        """
        Max 100 pts:
          Supertrend alignment (+ fresh-flip bonus)   30 + 5
          EMA 9/21 crossover + EMA 50 filter          15 + 10 + 5
          MACD (line + histogram)                     20
          Volume                                      15
          RSI                                         10
          ─────────────────────────────────────────── 110 → capped at 100
        """
        conf = 0.0

        # 1. Supertrend (30 pts + 5 bonus for fresh flip)
        st_dir  = ind.get("st_direction", 0)
        st_prev = ind.get("st_prev_dir",  0)
        if position_type == "LONG":
            if st_dir == 1:
                conf += 30
                if st_prev == -1:   # fresh bullish flip
                    conf += 5
        else:
            if st_dir == -1:
                conf += 30
                if st_prev == 1:    # fresh bearish flip
                    conf += 5

        # 2. EMA 9/21 + EMA 50 filter (up to 30 pts)
        ef, es, et = (ind.get("ema_fast"),
                      ind.get("ema_slow"),
                      ind.get("ema_trend"))
        efp, esp   = (ind.get("ema_fast_prev"),
                      ind.get("ema_slow_prev"))
        price = ind.get("last_close", 0)
        if ef and es and price:
            if position_type == "LONG":
                if ef > es:
                    conf += 15
                    if et and price > et:      # above EMA 50 = confirmed uptrend
                        conf += 10
                    if efp and esp and efp <= esp:  # fresh EMA cross-up
                        conf += 5
            else:
                if ef < es:
                    conf += 15
                    if et and price < et:
                        conf += 10
                    if efp and esp and efp >= esp:
                        conf += 5

        # 3. MACD (20 pts)
        macd = ind.get("macd", 0)
        sig  = ind.get("macd_signal", 0)
        hist = ind.get("macd_histogram", 0)
        if position_type == "LONG":
            if macd > sig and hist > 0:
                conf += 20
            elif macd > sig:
                conf += 10
        else:
            if macd < sig and hist < 0:
                conf += 20
            elif macd < sig:
                conf += 10

        # 4. Volume (15 pts)
        vr      = ind.get("volume_ratio", 0)
        min_vol = max(self.CONFIG["min_volume_ratio"], 0.01)
        if vr >= 1.0:
            conf += 15
        elif vr >= min_vol:
            conf += 15 * (vr / min_vol)

        # 5. RSI alignment (10 pts)
        rsi = ind.get("rsi", 50)
        ob  = self.CONFIG["rsi_overbought"]
        os  = self.CONFIG["rsi_oversold"]
        if position_type == "LONG":
            if rsi < os:
                conf += 10
            elif rsi < 55:
                conf += 10 * (55 - rsi) / (55 - os)
            elif rsi < ob:
                conf += max(0.0, 5 * (ob - rsi) / (ob - 55))
        else:
            if rsi > ob:
                conf += 10
            elif rsi > 45:
                conf += 10 * (rsi - 45) / (ob - 45)
            elif rsi > os:
                conf += max(0.0, 5 * (rsi - os) / (45 - os))

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
                 + self.CONFIG["st_period"] + 5)
        if len(candles) < min_c:
            return _null if return_confidence else None

        ind = self.compute_indicators(candles)
        if None in (ind["ema_fast"], ind["ema_slow"],
                    ind["ema_fast_prev"], ind["ema_slow_prev"]):
            return _null if return_confidence else None

        ef, es   = ind["ema_fast"],  ind["ema_slow"]
        efp, esp = ind["ema_fast_prev"], ind["ema_slow_prev"]
        macd     = ind["macd"]
        sig      = ind["macd_signal"]
        st_dir   = ind["st_direction"]
        st_prev  = ind["st_prev_dir"]
        atr      = ind["atr"]
        price    = ind["last_close"]
        vol_ok   = ind["volume_ratio"] >= self.CONFIG["min_volume_ratio"]

        # EMA crossover helpers
        ema_cross_up   = (efp <= esp) and (ef > es)
        ema_cross_down = (efp >= esp) and (ef < es)
        st_flip_bull   = (st_dir == 1  and st_prev == -1)
        st_flip_bear   = (st_dir == -1 and st_prev == 1)

        signal = None

        # ── LONG ─────────────────────────────────────────────────────────
        if (st_dir == 1
                and (ema_cross_up or st_flip_bull)
                and ef > es
                and macd >= sig
                and vol_ok):
            signal = "LONG"

        # ── SHORT ────────────────────────────────────────────────────────
        elif (st_dir == -1
              and (ema_cross_down or st_flip_bear)
              and ef < es
              and macd <= sig
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
            pos_size     = self.calculate_position_size(price, atr, ind["rsi"], signal)
            mult         = self.CONFIG["atr_multiplier"]
            trailing_stop = (round(price - atr * mult, 6) if signal == "LONG"
                             else round(price + atr * mult, 6))
            logger.info(
                f"[Enhanced v2 | Supertrend Trend] {signal} | "
                f"ST:{st_dir}(flip:{st_flip_bull or st_flip_bear}) "
                f"EMA:{ef:.4f}/{es:.4f}/{ind.get('ema_trend', 0):.4f} "
                f"MACD:{macd:.6f}/{sig:.6f} hist:{ind['macd_histogram']:.6f} "
                f"RSI:{ind['rsi']} Vol:{ind['volume_ratio']:.2f}x "
                f"ATR:{atr:.6f} Conf:{confidence:.1f}% AE:{auto_execute}"
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
