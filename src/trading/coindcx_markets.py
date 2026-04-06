"""Public CoinDCX market metadata (no API keys)."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

REST_BASE = "https://api.coindcx.com"
_CACHE: dict[str, Any] = {"ts": 0.0, "rows": None}
TTL_SEC = 300.0


def fetch_markets_details() -> list[dict[str, Any]]:
    """Raw list from GET /exchange/v1/markets_details."""
    url = f"{REST_BASE}/exchange/v1/markets_details"
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def get_markets_details_cached() -> list[dict[str, Any]]:
    now = time.time()
    if _CACHE["rows"] is not None and (now - float(_CACHE["ts"])) < TTL_SEC:
        return _CACHE["rows"]
    try:
        rows = fetch_markets_details()
    except Exception as e:
        logger.warning("markets_details fetch failed: %s", e)
        if _CACHE["rows"] is not None:
            return _CACHE["rows"]
        raise
    _CACHE["ts"] = now
    _CACHE["rows"] = rows
    return rows


def find_market_by_symbol(symbol: str, rows: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    sym = symbol.strip().upper()
    data = rows if rows is not None else get_markets_details_cached()
    for m in data:
        if (m.get("symbol") or "").strip().upper() == sym:
            return m
    return None


def runtime_pair_from_market_row(m: dict[str, Any]) -> dict[str, str]:
    """Build engine runtime pair dict from a markets_details row.

    CoinDCX uses ``base_currency_short_name`` as the *quote* (USDT or INR); target is the crypto.
    INR pairs have no Binance spot ticker — OHLC/LTP use CoinDCX public APIs only.
    TradingView widget uses a BINANCE:{TARGET}USDT *shape* proxy for chart only when quote is INR
    (not the INR price); execution prices are always from CoinDCX.
    """
    symbol = (m.get("symbol") or "").strip().upper()
    pair = (m.get("pair") or "").strip()
    ecode = (m.get("ecode") or "B").strip()
    quote = (m.get("base_currency_short_name") or "").strip().upper()
    target = (m.get("target_currency_short_name") or "").strip().upper()
    compact = symbol.replace("/", "").upper()
    if quote == "INR":
        binance_symbol = ""
        tv = f"BINANCE:{target}USDT" if target else f"BINANCE:{compact}"
    else:
        binance_symbol = compact
        tv = f"BINANCE:{binance_symbol}"
    if not quote:
        quote = "INR" if symbol.endswith("INR") else "USDT"
    return {
        "symbol": symbol,
        "pair": pair,
        "ecode": ecode,
        "binance_symbol": binance_symbol,
        "tradingview_symbol": tv,
        "quote_currency": quote,
    }


def list_tradable_markets(
    rows: list[dict[str, Any]] | None = None,
    *,
    quote_filter: str | None = None,
    query: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Active markets from CoinDCX ``markets_details``.

    ``quote_filter``: ``\"USDT\"``, ``\"INR\"``, or ``None`` for both (merged, sorted).
    """
    data = rows if rows is not None else get_markets_details_cached()
    q = query.strip().upper()
    quotes: set[str]
    if quote_filter is None or str(quote_filter).strip().lower() in ("", "all", "*"):
        quotes = {"USDT", "INR"}
    else:
        quotes = {str(quote_filter).strip().upper()}
    out: list[dict[str, Any]] = []
    for m in data:
        if m.get("status") != "active":
            continue
        bq = (m.get("base_currency_short_name") or "").strip().upper()
        if bq not in quotes:
            continue
        sym = (m.get("symbol") or "").strip().upper()
        if bq == "USDT" and not sym.endswith("USDT"):
            continue
        if bq == "INR" and not sym.endswith("INR"):
            continue
        if q and q not in sym:
            continue
        out.append(
            {
                "symbol": sym,
                "pair": m.get("pair"),
                "ecode": m.get("ecode"),
                "quote_currency": bq,
                "min_quantity": m.get("min_quantity"),
                "min_notional": m.get("min_notional"),
                "target_currency_short_name": m.get("target_currency_short_name"),
            }
        )
    out.sort(key=lambda x: x["symbol"])
    return out[: max(1, min(limit, 2000))]


def list_tradable_usdt_markets(
    rows: list[dict[str, Any]] | None = None,
    *,
    query: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Backward-compatible: USDT-quoted markets only."""
    return list_tradable_markets(rows, quote_filter="USDT", query=query, limit=limit)
