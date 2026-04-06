from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from typing import Any, Callable

from src.core.events import NewCandleEvent

logger = logging.getLogger(__name__)

_MAX_LEN = 2000


class DataManager:
    """In-memory OHLCV series keyed by (symbol, interval)."""

    def __init__(
        self,
        on_new_candle: Callable[[NewCandleEvent], None] | None = None,
        on_price_tick: Callable[[str, float], None] | None = None,
        *,
        coindcx_stream_updates_ltp: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self._series: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=_MAX_LEN))
        self._last_price: dict[str, float] = {}
        self.on_new_candle = on_new_candle
        self.on_price_tick = on_price_tick
        self._coindcx_stream_updates_ltp = coindcx_stream_updates_ltp

    def clear_all(self) -> None:
        """Drop all in-memory series and last prices (e.g. after switching pair)."""
        with self._lock:
            self._series.clear()
            self._last_price.clear()

    def last_price(self, symbol: str) -> float | None:
        with self._lock:
            return self._last_price.get(symbol)

    def set_last_price(self, symbol: str, price: float) -> None:
        with self._lock:
            self._last_price[symbol] = price

    def candles_df_rows(self, symbol: str, interval: str, n: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            q = self._series[(symbol, interval)]
            rows = list(q)[-n:]
        if not rows:
            return []
        return rows

    def ingest_candlestick_message(self, msg: dict[str, Any]) -> None:
        """Parse CoinDCX candlestick socket payload."""
        try:
            sym = (msg.get("s") or "").strip().upper()
            interval = msg.get("i") or "1m"
            closed = bool(msg.get("x"))
            o = float(msg["o"])
            h = float(msg["h"])
            l = float(msg["l"])
            c = float(msg["c"])
            v = float(msg.get("v") or 0)
            ts_start = int(msg.get("t") or 0)
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("skip bad candle msg: %s (%s)", msg, e)
            return

        row = {
            "timestamp": ts_start,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        }
        with self._lock:
            key = (sym, interval)
            deq = self._series[key]
            if deq and deq[-1]["timestamp"] == ts_start:
                deq[-1] = row
            else:
                deq.append(row)
            if self._coindcx_stream_updates_ltp:
                self._last_price[sym] = c

        if self.on_price_tick:
            try:
                self.on_price_tick(sym, float(msg.get("c")))
            except (TypeError, ValueError):
                pass

        if self.on_new_candle and closed:
            self.on_new_candle(
                NewCandleEvent(symbol=sym, interval=interval, candle=row, closed=True)
            )

    def bootstrap_from_rest(self, pair: str, symbol: str, intervals: list[str]) -> None:
        from src.data.historical import fetch_candles

        for iv in intervals:
            raw = fetch_candles(pair, interval=iv, limit=300)
            rows: list[dict[str, Any]] = []
            for x in raw:
                try:
                    if isinstance(x, dict):
                        rows.append(
                            {
                                "timestamp": int(x["time"]),
                                "open": float(x["open"]),
                                "high": float(x["high"]),
                                "low": float(x["low"]),
                                "close": float(x["close"]),
                                "volume": float(x.get("volume") or 0),
                            }
                        )
                    else:
                        rows.append(
                            {
                                "timestamp": int(x[0]),
                                "open": float(x[1]),
                                "high": float(x[2]),
                                "low": float(x[3]),
                                "close": float(x[4]),
                                "volume": float(x[5]) if len(x) > 5 else 0.0,
                            }
                        )
                except (IndexError, TypeError, ValueError, KeyError):
                    continue
            rows.sort(key=lambda r: r["timestamp"])
            with self._lock:
                deq = self._series[(symbol, iv)]
                deq.clear()
                for row in rows:
                    deq.append(row)
                if deq:
                    self._last_price[symbol] = deq[-1]["close"]
            logger.info("Bootstrapped %s %s with %s candles", symbol, iv, len(rows))

    def bootstrap_from_binance(self, binance_symbol: str, internal_symbol: str, intervals: list[str]) -> None:
        from src.data.historical import fetch_binance_klines

        sym = internal_symbol.strip().upper()
        for iv in intervals:
            raw = fetch_binance_klines(binance_symbol, iv, 500)
            rows: list[dict[str, Any]] = []
            for x in raw:
                try:
                    rows.append(
                        {
                            "timestamp": int(x[0]),
                            "open": float(x[1]),
                            "high": float(x[2]),
                            "low": float(x[3]),
                            "close": float(x[4]),
                            "volume": float(x[5]),
                        }
                    )
                except (IndexError, TypeError, ValueError):
                    continue
            rows.sort(key=lambda r: r["timestamp"])
            with self._lock:
                deq = self._series[(sym, iv)]
                deq.clear()
                for row in rows:
                    deq.append(row)
                if deq:
                    self._last_price[sym] = deq[-1]["close"]
            logger.info("Bootstrapped Binance %s %s with %s candles", sym, iv, len(rows))

    def ingest_binance_kline(self, internal_symbol: str, k: dict[str, Any]) -> None:
        """Apply one Binance kline object (the inner ``k`` field from stream payload)."""
        try:
            interval = k.get("i") or "1m"
            closed = bool(k.get("x"))
            ts_start = int(k["t"])
            o = float(k["o"])
            h = float(k["h"])
            l = float(k["l"])
            c = float(k["c"])
            v = float(k.get("v") or 0)
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("skip binance kline: %s (%s)", k, e)
            return

        sym = internal_symbol.strip().upper()
        row = {
            "timestamp": ts_start,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        }
        with self._lock:
            key = (sym, interval)
            deq = self._series[key]
            if deq and deq[-1]["timestamp"] == ts_start:
                deq[-1] = row
            else:
                deq.append(row)
            self._last_price[sym] = c

        if self.on_price_tick:
            try:
                self.on_price_tick(sym, c)
            except (TypeError, ValueError):
                pass

        if self.on_new_candle and closed:
            self.on_new_candle(
                NewCandleEvent(symbol=sym, interval=interval, candle=row, closed=True)
            )
