from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from config.settings import (
    DEFAULT_BINANCE_SYMBOL,
    DEFAULT_BOOTSTRAP_MARKET,
    DEFAULT_COINDCX_PAIR,
    DEFAULT_ECODE,
    DEFAULT_TRADINGVIEW_SYMBOL,
    Settings,
    get_settings,
)
from src.core.events import NewCandleEvent
from src.data.binance_stream import BinanceKlineStream
from src.data.data_manager import DataManager
from src.data.historical import (
    coindcx_candles_are_stale,
    fetch_binance_price,
    fetch_latest_close,
)
from src.data.websocket_client import CoinDCXStreamClient
from src.indicators.indicator_engine import IndicatorEngine
from src.persistence.database import init_db
from src.persistence.repository import Repository
from src.strategy.signal_detector import signal_from_indicator_output
from src.strategy.strategy_loader import load_strategy
from src.trading.coindcx_client import CoinDCXClient
from src.trading.coindcx_markets import (
    find_market_by_symbol,
    get_markets_details_cached,
    runtime_pair_from_market_row,
)
from src.trading.live_executor import LiveExecutor
from src.trading.order_executor import OrderExecutor
from src.trading.paper_executor import PaperExecutor
from src.trading.rate_limit import OrderRateLimiter
from src.trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

CONFIG_STRATEGY_INDICATOR = "strategy_indicator"
CONFIG_ACTIVE_PAIR = "active_pair"
CONFIG_SCALPER_ACTIVE = "scalper_active"
CONFIG_CHART_TIMEFRAME = "chart_timeframe"

# Binance kline intervals we support for OHLC + WS
_TIMEFRAMES_BINANCE = frozenset({"1m", "3m", "5m", "15m", "30m", "1h", "4h"})
# CoinDCX socket + public candles (subset)
_TIMEFRAMES_COINDCX = frozenset({"1m", "5m", "15m", "1h"})

_TRADINGVIEW_INTERVAL = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
}


def _tf_sort_key(tf: str) -> tuple[int, str]:
    order = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
    return (order.get(tf, 99), tf)


class TradingEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.repo = Repository()
        if self.repo.get_config("trading_mode") is None:
            self.repo.set_config("trading_mode", "paper")

        self._pair_lock = threading.RLock()
        self._runtime_pair: dict[str, str] = self._load_runtime_pair()

        self.strategy = load_strategy(ROOT / "config" / "strategies" / "default.json")
        self.indicator_dir = ROOT / "src" / "indicators" / "user_indicators"
        self.indicator_engine = IndicatorEngine(self.indicator_dir)

        self.data = DataManager(
            on_new_candle=self._on_new_candle,
            on_price_tick=self._on_price_tick,
        )
        self.risk = RiskManager(self.settings)
        self.paper = PaperExecutor(self.settings, self.repo)
        limiter = OrderRateLimiter(
            self.settings.order_rate_limit,
            float(self.settings.order_rate_window_sec),
        )
        self.coindcx = CoinDCXClient(self.settings, rate_limiter=limiter)
        self.live = LiveExecutor(self.settings, self.coindcx, self.repo)
        self.orders = OrderExecutor(
            self.settings,
            self.repo,
            self.risk,
            self.paper,
            self.live,
            self.data,
        )

        self._use_binance_ohlc = self._compute_use_binance_ohlc()
        self.stream: CoinDCXStreamClient | None = None
        self.binance_stream: BinanceKlineStream | None = None
        self._ltp_source: str = "binance"
        self._attach_market_streams()

    def _load_runtime_pair(self) -> dict[str, str]:
        raw = self.repo.get_config(CONFIG_ACTIVE_PAIR)
        if raw:
            try:
                d = json.loads(raw)
                if isinstance(d, dict) and d.get("symbol"):
                    return self._validate_runtime_pair(d)
            except json.JSONDecodeError:
                pass
        return self._bootstrap_runtime_pair_from_env()

    def _validate_runtime_pair(self, d: dict) -> dict[str, str]:
        sym = str(d.get("symbol", "")).strip().upper()
        pair = str(d.get("pair", "")).strip()
        ecode = str(d.get("ecode", DEFAULT_ECODE)).strip()
        qc = str(d.get("quote_currency", "")).strip().upper()
        if not qc and sym.endswith("INR"):
            qc = "INR"
        if not qc:
            qc = "USDT"
        b = str(d.get("binance_symbol", sym if qc != "INR" else "")).strip().upper()
        tv = str(d.get("tradingview_symbol", f"BINANCE:{b or sym}")).strip()
        if not sym:
            return self._bootstrap_runtime_pair_from_env()
        return {
            "symbol": sym,
            "pair": pair or self._pair_channel_fallback(sym),
            "ecode": ecode,
            "binance_symbol": b,
            "tradingview_symbol": tv,
            "quote_currency": qc,
        }

    def quote_currency(self) -> str:
        qc = (self._runtime_pair.get("quote_currency") or "").strip().upper()
        if qc:
            return qc
        sym = (self._runtime_pair.get("symbol") or "").strip().upper()
        if sym.endswith("INR"):
            return "INR"
        return "USDT"

    def _compute_use_binance_ohlc(self) -> bool:
        """INR pairs have no Binance spot OHLC — always CoinDCX public data."""
        if self.quote_currency() == "INR":
            return False
        return self._resolve_use_binance_ohlc()

    def _pair_channel_fallback(self, symbol: str) -> str:
        s = symbol.replace("/", "").upper()
        if s.endswith("USDT"):
            base = s[: -4]
            return f"{DEFAULT_ECODE}-{base}_USDT"
        if s.endswith("INR"):
            base = s[: -3]
            return f"I-{base}_INR"
        return DEFAULT_COINDCX_PAIR

    def _bootstrap_runtime_pair_from_env(self) -> dict[str, str]:
        want = DEFAULT_BOOTSTRAP_MARKET.strip().upper()
        try:
            m = find_market_by_symbol(want)
            if m:
                rp = runtime_pair_from_market_row(m)
                self.repo.set_config(CONFIG_ACTIVE_PAIR, json.dumps(rp))
                logger.info("Saved active pair from CoinDCX metadata: %s", rp["symbol"])
                return rp
        except Exception as e:
            logger.warning("Could not load market metadata for %s: %s", want, e)
        rp = {
            "symbol": want,
            "pair": DEFAULT_COINDCX_PAIR,
            "ecode": DEFAULT_ECODE,
            "binance_symbol": DEFAULT_BINANCE_SYMBOL,
            "tradingview_symbol": DEFAULT_TRADINGVIEW_SYMBOL,
            "quote_currency": "USDT",
        }
        self.repo.set_config(CONFIG_ACTIVE_PAIR, json.dumps(rp))
        return rp

    def _bootstrap_intervals(self) -> list[str]:
        eff = self.effective_chart_timeframe()
        base = ["1m", "5m", "15m", "1h"]
        if self._use_binance_ohlc:
            base = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
        out: list[str] = []
        seen: set[str] = set()
        for x in [eff] + base:
            if x in self._allowed_timeframes() and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def _attach_market_streams(self) -> None:
        if self._use_binance_ohlc:
            bin_iv = self.effective_chart_timeframe()
            self.binance_stream = BinanceKlineStream(
                self._runtime_pair["binance_symbol"],
                bin_iv,
                self._on_binance_kline,
            )
            logger.warning(
                "OHLC feed: Binance %s @ %s (TradingView-aligned). Live orders use CoinDCX API for %s.",
                self._runtime_pair["binance_symbol"],
                bin_iv,
                self._runtime_pair["symbol"],
            )
        else:
            channels = [
                f"{self._runtime_pair['pair']}_{tf}"
                for tf in ("1m", "5m", "15m", "1h")
            ]
            self.stream = CoinDCXStreamClient(
                self.settings,
                channels,
                on_candlestick=self.data.ingest_candlestick_message,
            )
            logger.info("OHLC feed: CoinDCX Socket.IO + public REST bootstrap (%s)", self._runtime_pair["pair"])

    def active_market(self) -> str:
        return self._runtime_pair["symbol"]

    def active_ecode(self) -> str:
        return self._runtime_pair["ecode"]

    def active_tradingview_symbol(self) -> str:
        return self._runtime_pair["tradingview_symbol"]

    def runtime_pair_public_view(self) -> dict[str, str]:
        return dict(self._runtime_pair)

    def scalper_active(self) -> bool:
        v = self.repo.get_config(CONFIG_SCALPER_ACTIVE, "0")
        return str(v).lower() in ("1", "true", "yes", "on")

    def _stored_chart_timeframe(self) -> str | None:
        v = self.repo.get_config(CONFIG_CHART_TIMEFRAME)
        if v and str(v).strip():
            return self._normalize_timeframe(str(v).strip())
        return None

    def stored_chart_timeframe(self) -> str | None:
        """User-selected timeframe when scalper is off (SQLite); None if using strategy default."""
        return self._stored_chart_timeframe()

    def _normalize_timeframe(self, raw: str) -> str:
        x = raw.strip().lower().replace(" ", "")
        aliases = {"60m": "1h", "60": "1h", "240m": "4h", "h1": "1h", "h4": "4h"}
        if x in aliases:
            x = aliases[x]
        return x

    def _allowed_timeframes(self) -> frozenset[str]:
        return _TIMEFRAMES_BINANCE if self._use_binance_ohlc else _TIMEFRAMES_COINDCX

    def effective_chart_timeframe(self) -> str:
        if self.scalper_active():
            return "1m"
        stored = self._stored_chart_timeframe()
        if stored and stored in self._allowed_timeframes():
            return stored
        stf = (self.strategy.get("timeframe") or "1m").strip().lower()
        stf = self._normalize_timeframe(stf)
        if stf in self._allowed_timeframes():
            return stf
        return "5m" if "5m" in self._allowed_timeframes() else "1m"

    def tradingview_interval(self) -> str:
        tf = self.effective_chart_timeframe()
        return _TRADINGVIEW_INTERVAL.get(tf, "60")

    def allowed_timeframes_list(self) -> list[str]:
        return sorted(self._allowed_timeframes(), key=_tf_sort_key)

    def apply_trading_style(
        self,
        *,
        scalper: bool | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        if scalper is not None:
            self.repo.set_config(CONFIG_SCALPER_ACTIVE, "1" if scalper else "0")
        if timeframe is not None:
            tf = self._normalize_timeframe(str(timeframe).strip())
            if tf not in self._allowed_timeframes():
                return {
                    "ok": False,
                    "error": f"invalid_timeframe:{tf}",
                    "allowed": self.allowed_timeframes_list(),
                }
            self.repo.set_config(CONFIG_CHART_TIMEFRAME, tf)
        eff = self.effective_chart_timeframe()
        with self._pair_lock:
            self.stop_streams()
            self.data.clear_all()
            self._attach_market_streams()
            self.start()
        logger.info(
            "Trading style: scalper=%s stored_tf=%s effective_tf=%s",
            self.scalper_active(),
            self._stored_chart_timeframe(),
            eff,
        )
        return {
            "ok": True,
            "scalper_active": self.scalper_active(),
            "chart_timeframe": self._stored_chart_timeframe(),
            "effective_timeframe": eff,
            "allowed_timeframes": self.allowed_timeframes_list(),
        }

    def _scalper_tp_sl_prices(self, sym: str, signal: str) -> tuple[float | None, float | None]:
        """TP/SL distance = sum of (high-low) of last two completed 1m candles."""
        rows = self.data.candles_df_rows(sym, "1m", n=8)
        if len(rows) < 2:
            return None, None
        r1, r2 = rows[-1], rows[-2]
        try:
            b1 = float(r1["high"]) - float(r1["low"])
            b2 = float(r2["high"]) - float(r2["low"])
            band = b1 + b2
        except (TypeError, ValueError, KeyError):
            return None, None
        if band <= 0:
            return None, None
        entry = self.data.last_price(sym)
        if entry is None or entry <= 0:
            try:
                entry = float(rows[-1]["close"])
            except (TypeError, ValueError, KeyError):
                return None, None
        if signal == "buy":
            return entry + band, entry - band
        if signal == "sell":
            return entry - band, entry + band
        return None, None

    def stop_streams(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream = None
        if self.binance_stream:
            self.binance_stream.stop()
            self.binance_stream = None

    def reconfigure_pair(self, symbol: str) -> dict:
        """Switch tradable pair: stop feeds, clear OHLC cache, reset paper state, restart feeds."""
        sym = symbol.strip().upper()
        if not sym:
            return {"ok": False, "error": "empty_symbol"}
        try:
            rows = get_markets_details_cached()
        except Exception as e:
            return {"ok": False, "error": f"markets_unavailable: {e}"}
        m = find_market_by_symbol(sym, rows=rows)
        if not m:
            return {"ok": False, "error": "unknown_symbol"}
        if (m.get("status") or "").lower() != "active":
            return {"ok": False, "error": "market_not_active"}
        new_rp = runtime_pair_from_market_row(m)
        with self._pair_lock:
            self.stop_streams()
            self._runtime_pair = new_rp
            self.repo.set_config(CONFIG_ACTIVE_PAIR, json.dumps(new_rp))
            self.paper.positions.clear()
            self.paper.virtual_balance = self.settings.paper_trading_balance
            n_closed = self.repo.reconcile_paper_trades_not_in_memory(set())
            if n_closed:
                logger.info(
                    "Pair change: closed %d paper open row(s) in SQLite (memory reset)",
                    n_closed,
                )
            self.data.clear_all()
            self._use_binance_ohlc = self._compute_use_binance_ohlc()
            self._attach_market_streams()
            self.start()
        logger.info("Reconfigured trading pair to %s (%s)", new_rp["symbol"], new_rp["pair"])
        return {"ok": True, "pair": new_rp}

    def _resolve_use_binance_ohlc(self) -> bool:
        src = self.settings.ohlc_source
        if src == "binance":
            return True
        if src == "coindcx":
            return False
        max_age_ms = max(30, self.settings.coindcx_max_candle_age_sec) * 1000
        stale = coindcx_candles_are_stale(self.rest_pair(), max_age_ms=max_age_ms)
        if stale:
            logger.warning(
                "Auto-selected Binance OHLC: CoinDCX public candle older than %ss for %s",
                self.settings.coindcx_max_candle_age_sec,
                self.rest_pair(),
            )
        return stale

    def start(self) -> None:
        sym = self.strategy_symbol()
        intervals = self._bootstrap_intervals()
        if self._use_binance_ohlc:
            self.data.bootstrap_from_binance(
                self._runtime_pair["binance_symbol"],
                sym,
                intervals,
            )
            if self.binance_stream:
                self.binance_stream.start_background()
        else:
            self.data.bootstrap_from_rest(
                self.rest_pair(),
                sym,
                intervals,
            )
            if self.stream:
                self.stream.start_background()
        self.refresh_last_price_from_public()
        logger.info("Trading engine started")

    def _on_binance_kline(self, k: dict) -> None:
        self.data.ingest_binance_kline(self.strategy_symbol(), k)

    def _on_price_tick(self, symbol: str, ltp: float) -> None:
        if self.orders.current_mode() != "paper":
            return
        sym = self.strategy_symbol()
        if sym.replace("_", "").upper() != symbol.replace("_", "").upper():
            return
        px = self.data.last_price(sym)
        if px and px > 0:
            self.paper.on_price(sym, px)
        else:
            self.paper.on_price(sym, ltp)

    def _effective_indicator(self) -> str:
        v = self.repo.get_config(CONFIG_STRATEGY_INDICATOR)
        if v and str(v).strip():
            return str(v).strip()
        # Prefer saved Pine translation (active.py) when present — no separate JSON strategy needed.
        if (self.indicator_dir / "active.py").is_file():
            return "user:active"
        return str(self.strategy.get("indicator", "user:active"))

    def _on_new_candle(self, ev: NewCandleEvent) -> None:
        if not ev.closed:
            return
        sym = self.strategy_symbol()
        evs = ev.symbol.strip().upper().replace("_", "")
        if evs != sym.replace("_", ""):
            return
        tf = self.effective_chart_timeframe()
        if ev.interval != tf:
            return
        rows = self.data.candles_df_rows(sym, ev.interval, n=500)
        closes = [float(r["close"]) for r in rows]
        ind = self._effective_indicator()
        min_bars = 20 if ind == "builtin_rsi" else 5
        if len(closes) < min_bars:
            return
        params = dict(self.strategy.get("params") or {})
        if ind.startswith("user:"):
            params = {}
        vals = self.indicator_engine.compute(
            indicator=ind,
            params=params,
            closes=closes,
        )
        sig = signal_from_indicator_output(
            indicator=ind, values=vals, strategy=self.strategy
        )
        if sig:
            logger.info("signal %s indicator=%s vals=%s", sig, ind, vals)
            self.repo.add_signal(
                symbol=sym,
                signal_type=sig,
                indicator_name=ind,
                strength=None,
                indicator_values=vals,
            )
            if self.settings.auto_trade_enabled:
                tp_px: float | None = None
                sl_px: float | None = None
                if self.scalper_active():
                    tp_px, sl_px = self._scalper_tp_sl_prices(sym, sig)
                self.orders.on_signal(
                    signal=sig,
                    symbol=sym,
                    market=self.active_market(),
                    quantity=self.settings.default_order_quantity,
                    leverage=self.settings.default_leverage,
                    ecode=self.active_ecode(),
                    tp_price=tp_px,
                    sl_price=sl_px,
                )

    def rest_pair(self) -> str:
        return self._runtime_pair["pair"]

    def strategy_symbol(self) -> str:
        return self.active_market()

    def close_paper_position(self, trade_id: str) -> dict[str, Any]:
        """Market-close a single open paper position (dashboard)."""
        if self.orders.current_mode() != "paper":
            return {"ok": False, "error": "paper_only"}
        tid = str(trade_id).strip()
        if not tid:
            return {"ok": False, "error": "missing_trade_id"}
        pos = self.paper.positions.get(tid)
        if not pos:
            return {"ok": False, "error": "position_not_found"}
        self.refresh_last_price_from_public()
        ltp = self.data.last_price(pos.symbol) or 0.0
        if ltp <= 0:
            return {"ok": False, "error": "no_last_price"}
        return self.paper.close_at_market(trade_id=tid, ltp=ltp)

    def refresh_last_price_from_public(self) -> float | None:
        """Update LTP: Binance spot when quote is USDT; INR pairs use CoinDCX public candles only."""
        sym = self.strategy_symbol()
        if self.quote_currency() == "INR":
            px_cd = fetch_latest_close(self.rest_pair(), interval="1m")
            if px_cd and px_cd > 0:
                self.data.set_last_price(sym, px_cd)
                self._ltp_source = "coindcx_rest"
                return self.data.last_price(sym)
            self._ltp_source = "none"
            return self.data.last_price(sym)

        bsym = (self._runtime_pair.get("binance_symbol") or "").strip()
        if bsym:
            px = fetch_binance_price(bsym)
            if px and px > 0:
                self.data.set_last_price(sym, px)
                self._ltp_source = "binance"
                return self.data.last_price(sym)

        now_ms = int(time.time() * 1000)
        max_age_ms = max(30, self.settings.coindcx_max_candle_age_sec) * 1000
        from src.data.historical import coindcx_newest_candle_open_time_ms

        ct = coindcx_newest_candle_open_time_ms(self.rest_pair(), "1m")
        fresh_coindcx = ct is not None and (now_ms - ct) <= max_age_ms
        if fresh_coindcx:
            px_cd = fetch_latest_close(self.rest_pair(), interval="1m")
            if px_cd and px_cd > 0:
                self.data.set_last_price(sym, px_cd)
                self._ltp_source = "coindcx_rest"
                return self.data.last_price(sym)

        self._ltp_source = "none"
        return self.data.last_price(sym)

    def analysis_snapshot(self) -> dict:
        sym = self.strategy_symbol()
        tf = self.effective_chart_timeframe()
        rows = self.data.candles_df_rows(sym, tf, n=500)
        closes = [float(r["close"]) for r in rows]
        ind = self._effective_indicator()
        params = dict(self.strategy.get("params") or {})
        if ind.startswith("user:"):
            params = {}
        values: dict = {}
        if len(closes) >= 5:
            values = self.indicator_engine.compute(
                indicator=ind,
                params=params,
                closes=closes,
            )
        ltp = self.data.last_price(sym)
        rules_view: dict[str, Any] | str
        if ind.startswith("user:"):
            rules_view = {
                "source": "pine",
                "detail": "Signals come from Pine via active.py compute() — use keys signal or buy/sell.",
            }
        else:
            rules_view = dict(self.strategy.get("rules") or {})
        return {
            "symbol": sym,
            "timeframe": tf,
            "candles_loaded": len(closes),
            "last_close": closes[-1] if closes else None,
            "last_price_cache": ltp,
            "indicator": ind,
            "params": params,
            "values": values,
            "rules": rules_view,
            "ohlc_feed": "binance" if self._use_binance_ohlc else "coindcx",
            "binance_symbol": self._runtime_pair["binance_symbol"],
            "coindcx_pair": self.rest_pair(),
            "tradingview_symbol": self._runtime_pair["tradingview_symbol"],
            "quote_currency": self.quote_currency(),
            "chart_note": (
                "Chart uses the coin's USDT pair as a visual proxy; LTP and orders are INR on CoinDCX."
                if self.quote_currency() == "INR"
                else ""
            ),
            "scalper_active": self.scalper_active(),
            "effective_timeframe": tf,
            "chart_timeframe_stored": self._stored_chart_timeframe(),
            "ltp_source": self._ltp_source,
        }

    def stop(self) -> None:
        self.stop_streams()
        self.repo.close()


def build_engine() -> TradingEngine:
    init_db()
    return TradingEngine()
