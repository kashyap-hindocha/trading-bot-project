from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

PUBLIC_BASE = "https://public.coindcx.com"
BINANCE_API = "https://api.binance.com"


def fetch_candles(pair: str, interval: str = "1m", limit: int = 500) -> list[dict[str, Any]]:
    """Fetch historical OHLCV from CoinDCX public REST (spot market data)."""
    url = f"{PUBLIC_BASE}/market_data/candles"
    try:
        r = requests.get(
            url,
            params={"pair": pair, "interval": interval, "limit": limit},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        logger.warning("fetch_candles failed: %s", e)
        return []


def coindcx_newest_candle_open_time_ms(pair: str, interval: str = "1m") -> int | None:
    rows = fetch_candles(pair, interval=interval, limit=1)
    if not rows:
        return None
    r = rows[0]
    try:
        if isinstance(r, dict):
            return int(r["time"])
        return int(r[0])
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def coindcx_candles_are_stale(pair: str, max_age_ms: int, interval: str = "1m") -> bool:
    """True if newest CoinDCX candle open time is older than max_age_ms (public feed frozen/stale)."""
    t = coindcx_newest_candle_open_time_ms(pair, interval)
    if t is None:
        return True
    now_ms = int(time.time() * 1000)
    return (now_ms - t) > max_age_ms


def fetch_binance_klines(symbol: str, interval: str, limit: int = 500) -> list[list[Any]]:
    """Raw Binance kline rows: [openTime, o, h, l, c, vol, ...]."""
    try:
        r = requests.get(
            f"{BINANCE_API}/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("fetch_binance_klines failed: %s", e)
        return []


def fetch_binance_price(symbol: str) -> float | None:
    """Spot last price (aligns with TradingView BTCUSDT / Binance)."""
    try:
        r = requests.get(
            f"{BINANCE_API}/api/v3/ticker/price",
            params={"symbol": symbol.upper()},
            timeout=15,
        )
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        logger.warning("fetch_binance_price failed: %s", e)
        return None


def fetch_latest_close(pair: str, interval: str = "1m") -> float | None:
    """Latest candle close from CoinDCX public REST (often stale; prefer Binance helpers)."""
    rows = fetch_candles(pair, interval=interval, limit=1)
    if not rows:
        return None
    first = rows[0]
    try:
        if isinstance(first, dict):
            return float(first["close"])
        return float(first[4])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
