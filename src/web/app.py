from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.core.engine import CONFIG_STRATEGY_INDICATOR, TradingEngine
from src.indicators import pine_translator
from src.persistence.repository import Repository
from src.trading.coindcx_markets import list_tradable_markets

ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "src" / "web" / "templates"))

CONFIG_PINE_DRAFT = "pine_editor_draft"
CONFIG_PINE_NAME = "pine_editor_name"


def _safe_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    if isinstance(v, str) and not v.strip():
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _utc_day(d: datetime | None):
    if d is None:
        return None
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc).date()
    return d.astimezone(timezone.utc).date()


def _ltp_for_position(eng: TradingEngine, strategy_sym: str, position_symbol: str) -> float:
    """Last price for a position's symbol (falls back to active pair)."""
    ps = (position_symbol or strategy_sym).strip().upper()
    px = eng.data.last_price(ps)
    if px is not None and px > 0:
        return float(px)
    px2 = eng.data.last_price(strategy_sym.strip().upper())
    if px2 is not None and px2 > 0:
        return float(px2)
    return 0.0


def _position_ltp_and_unrealized(
    eng: TradingEngine, strategy_sym: str, p: dict[str, Any]
) -> tuple[float, float]:
    """Returns (ltp, unrealized_usdt). ltp is 0.0 if no price."""
    px = _ltp_for_position(eng, strategy_sym, str(p.get("symbol", "")))
    if px <= 0:
        return 0.0, 0.0
    q = float(p["quantity"])
    e = float(p["entry"])
    if p["side"] == "buy":
        u = (px - e) * q
    else:
        u = (e - px) * q
    return px, u


def _sum_unrealized(eng: TradingEngine, strategy_sym: str, positions: list[dict[str, Any]]) -> float:
    u = 0.0
    for p in positions:
        px, row_u = _position_ltp_and_unrealized(eng, strategy_sym, p)
        if px <= 0:
            continue
        u += row_u
    return u


def _enrich_open_positions_with_ltp(
    eng: TradingEngine, strategy_sym: str, positions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach per-row ltp and unrealized_pnl for dashboard table."""
    out: list[dict[str, Any]] = []
    for raw in positions:
        row = dict(raw)
        ltp, unreal = _position_ltp_and_unrealized(eng, strategy_sym, raw)
        if ltp > 0:
            row["ltp"] = ltp
            row["unrealized_pnl"] = unreal
        else:
            row["ltp"] = None
            row["unrealized_pnl"] = None
        out.append(row)
    return out


def _margin_locked_usdt(positions: list[dict[str, Any]]) -> float:
    """Initial margin locked for open positions (notional / leverage)."""
    t = 0.0
    for p in positions:
        q = float(p["quantity"])
        e = float(p["entry"])
        lev = max(int(p.get("leverage") or 1), 1)
        t += abs(q * e) / lev
    return t


def _live_open_positions_rows(repo: Repository) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in repo.list_open_trades(is_paper=False):
        rows.append(
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "entry": t.price,
                "leverage": t.leverage,
                "tp_price": None,
                "sl_price": None,
            }
        )
    return rows


def build_dashboard_payload(eng: TradingEngine, *, refresh_reference_price: bool = False) -> dict[str, Any]:
    """Shared JSON for /api/status and WebSocket. When refresh_reference_price, pulls Binance LTP (TradingView-aligned)."""
    if refresh_reference_price:
        eng.refresh_last_price_from_public()
    sym = eng.strategy_symbol()
    ltp = eng.data.last_price(sym) or 0.0
    analysis = eng.analysis_snapshot()
    with Repository() as repo:
        mode = repo.get_trading_mode() or "paper"
        trades = repo.list_trades(paper=(mode == "paper"), limit=80)
        signals = repo.recent_signals(limit=20)
        if mode == "paper":
            pos = eng.paper.open_positions_view()
        else:
            pos = _live_open_positions_rows(repo)

    pos = _enrich_open_positions_with_ltp(eng, sym, pos)

    today_utc = datetime.now(timezone.utc).date()
    closed_today = [
        t
        for t in trades
        if t.status == "closed" and _utc_day(t.closed_at) == today_utc
    ]
    wins_today = sum(1 for t in closed_today if (t.pnl or 0) > 0)

    unrealized = _sum_unrealized(eng, sym, pos)
    margin_locked = _margin_locked_usdt(pos) if mode == "paper" else 0.0
    paper_free = eng.paper.virtual_balance if mode == "paper" else None
    paper_equity = (paper_free + margin_locked + unrealized) if mode == "paper" and paper_free is not None else None

    return {
        "type": "dashboard",
        "ts_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "mode": mode,
        "symbol": sym,
        "tradingview_symbol": eng.active_tradingview_symbol(),
        "runtime_pair": eng.runtime_pair_public_view(),
        "quote_currency": eng.quote_currency(),
        "balance_paper": paper_equity,
        "balance_paper_free": paper_free,
        "balance_paper_equity": paper_equity,
        "margin_locked_paper": margin_locked if mode == "paper" else None,
        "last_price": ltp,
        "unrealized_pnl": unrealized,
        "unrealized_pnl_paper": unrealized if mode == "paper" else None,
        "open_positions": pos,
        "default_leverage": eng.settings.default_leverage,
        "ohlc_feed": analysis.get("ohlc_feed"),
        "analysis": analysis,
        "signals": [
            {
                "symbol": s.symbol,
                "type": s.signal_type,
                "time": s.timestamp.isoformat() if s.timestamp else "",
                "indicator": s.indicator_name,
            }
            for s in signals
        ],
        "trades_recent": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.quantity,
                "price": t.price,
                "status": t.status,
                "pnl": t.pnl,
                "paper": t.is_paper,
                "created": t.created_at.isoformat() if t.created_at else "",
            }
            for t in trades
        ],
        "stats_today": {
            "closed_count": len(closed_today),
            "wins": wins_today,
            "win_rate_pct": (100.0 * wins_today / len(closed_today)) if closed_today else None,
        },
        "scalper_active": eng.scalper_active(),
        "chart_timeframe": eng.stored_chart_timeframe(),
        "effective_timeframe": eng.effective_chart_timeframe(),
        "allowed_timeframes": eng.allowed_timeframes_list(),
        "tradingview_interval": eng.tradingview_interval(),
    }


def create_app(engine: TradingEngine) -> FastAPI:
    app = FastAPI(title="CoinDCX Algo Trader")
    app.state.engine = engine
    static_dir = ROOT / "src" / "web" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        with Repository() as repo:
            mode = repo.get_trading_mode() or "paper"
        eng = app.state.engine
        eng.refresh_last_price_from_public()
        ltp = eng.data.last_price(eng.strategy_symbol()) or 0.0
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "mode": mode,
                "symbol": eng.strategy_symbol(),
                "ltp": ltp,
                "default_leverage": eng.settings.default_leverage,
                "tradingview_symbol": eng.active_tradingview_symbol(),
                "tradingview_interval": eng.tradingview_interval(),
                "scalper_active": eng.scalper_active(),
                "chart_timeframe": eng.stored_chart_timeframe(),
                "effective_timeframe": eng.effective_chart_timeframe(),
                "allowed_timeframes": eng.allowed_timeframes_list(),
            },
        )

    @app.get("/api/trading-style")
    def api_trading_style_get():
        eng = app.state.engine
        return {
            "ok": True,
            "scalper_active": eng.scalper_active(),
            "chart_timeframe": eng.stored_chart_timeframe(),
            "effective_timeframe": eng.effective_chart_timeframe(),
            "allowed_timeframes": eng.allowed_timeframes_list(),
            "tradingview_interval": eng.tradingview_interval(),
        }

    @app.post("/api/trading-style")
    def api_trading_style_post(body: dict):
        eng = app.state.engine
        raw_sc = body.get("scalper")
        if raw_sc is None:
            scalper: bool | None = None
        elif isinstance(raw_sc, str):
            scalper = raw_sc.lower() in ("1", "true", "yes", "on")
        else:
            scalper = bool(raw_sc)
        raw_tf = body.get("timeframe") or body.get("chart_timeframe")
        timeframe = str(raw_tf).strip() if raw_tf is not None and str(raw_tf).strip() else None
        if scalper is None and timeframe is None:
            return {
                "ok": True,
                "scalper_active": eng.scalper_active(),
                "chart_timeframe": eng.stored_chart_timeframe(),
                "effective_timeframe": eng.effective_chart_timeframe(),
                "allowed_timeframes": eng.allowed_timeframes_list(),
                "unchanged": True,
            }
        out = eng.apply_trading_style(scalper=scalper, timeframe=timeframe)
        return JSONResponse(out, status_code=200 if out.get("ok") else 400)

    @app.get("/api/markets")
    def api_markets(q: str = "", limit: int = 2000, quote: str = "all"):
        """``quote``: ``all`` | ``usdt`` | ``inr`` (case-insensitive)."""
        try:
            qf = str(quote).strip().lower()
            if qf in ("all", "*", ""):
                quote_filter = None
            elif qf in ("usdt", "inr"):
                quote_filter = qf.upper()
            else:
                return JSONResponse({"ok": False, "error": "quote must be all, usdt, or inr"}, status_code=400)
            rows = list_tradable_markets(
                quote_filter=quote_filter,
                query=q,
                limit=min(max(limit, 1), 2000),
            )
            return {"ok": True, "markets": rows, "quote_filter": quote_filter or "all"}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=502)

    @app.get("/api/pair/current")
    def api_pair_current():
        eng = app.state.engine
        return {"ok": True, "pair": eng.runtime_pair_public_view()}

    @app.post("/api/pair")
    def api_pair_set(body: dict):
        sym = str(body.get("symbol", "")).strip()
        eng = app.state.engine
        out = eng.reconfigure_pair(sym)
        return JSONResponse(out, status_code=200 if out.get("ok") else 400)

    @app.get("/api/status")
    def api_status():
        eng = app.state.engine
        return build_dashboard_payload(eng, refresh_reference_price=True)

    @app.websocket("/ws/dashboard")
    async def ws_dashboard(websocket: WebSocket) -> None:
        await websocket.accept()
        eng = app.state.engine
        try:
            while True:
                try:
                    payload = build_dashboard_payload(eng, refresh_reference_price=True)
                    await websocket.send_json(payload)
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
                await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            pass

    @app.get("/api/trades")
    def api_trades(paper: bool | None = None):
        with Repository() as repo:
            rows = repo.list_trades(paper=paper, limit=200)
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "leverage": t.leverage,
                "pnl": t.pnl,
                "is_paper": t.is_paper,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in rows
        ]

    @app.get("/api/indicator/active")
    def api_indicator_active():
        with Repository() as repo:
            code = repo.get_config(CONFIG_PINE_DRAFT, "") or ""
            name = repo.get_config(CONFIG_PINE_NAME, "user") or "user"
        return {"pine_code": code, "name": name}

    @app.post("/api/mode")
    def api_mode(body: dict):
        mode = str(body.get("mode", "paper")).lower()
        if mode not in ("paper", "live"):
            return JSONResponse({"ok": False, "error": "invalid mode"}, status_code=400)
        app.state.engine.orders.set_mode(mode)
        return {"ok": True, "mode": mode}

    @app.post("/api/indicator/upload")
    def api_indicator_upload(body: dict):
        """Save Pine draft; compile via pine2py; require valid Python with ``compute()`` before activating."""
        name = str(body.get("name", "user")).strip()
        code = str(body.get("pine_code", ""))
        if not code.strip():
            return JSONResponse({"ok": False, "error": "empty pine_code"}, status_code=400)
        with Repository() as repo:
            repo.set_config(CONFIG_PINE_DRAFT, code)
            repo.set_config(CONFIG_PINE_NAME, name)
        path = pine_translator.save_user_indicator(name, code, engine.indicator_dir)

        py, err = pine_translator.try_translate_pine(code)
        if not py:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "pine_compile_failed",
                    "translate_error": err,
                    "path": str(path),
                    "hint": "Pine saved as draft. Install deps (pip install -r requirements.txt) and fix script until compile succeeds.",
                },
                status_code=422,
            )

        final_py = py
        ok, detail = pine_translator.validate_translated_python_has_compute(
            final_py, engine.indicator_dir
        )
        if not ok:
            bridged = pine_translator.ensure_compute_entrypoint(py)
            ok2, detail2 = pine_translator.validate_translated_python_has_compute(
                bridged, engine.indicator_dir
            )
            if ok2:
                final_py = bridged
            else:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "pine_validation_failed",
                        "detail": detail2 or detail,
                        "path": str(path),
                        "hint": "Pine saved as draft. Fix translator output or edit user_indicators/active.py after a successful compile.",
                    },
                    status_code=422,
                )

        with Repository() as repo:
            pine_translator.save_user_indicator("active", code, engine.indicator_dir)
            pine_translator.save_python_source("active", final_py, engine.indicator_dir)
            repo.set_config(CONFIG_STRATEGY_INDICATOR, "user:active")
        return {
            "ok": True,
            "path": str(path),
            "translated": True,
            "translate_error": None,
            "strategy_active_indicator": "user:active",
            "bridge_appended": final_py != py,
            "hint": (
                "Compile OK — only your Pine drives signals. "
                + (
                    "A default compute() stub was appended — edit active.py to wire your Pine logic to signal/buy/sell. "
                    if final_py != py
                    else "compute() must return signal/buy/sell for the last closed bar. "
                )
            ).strip(),
        }

    def _api_order_close_impl(body: dict) -> JSONResponse:
        tid = str(body.get("trade_id", "")).strip()
        if not tid:
            return JSONResponse({"ok": False, "error": "missing trade_id"}, status_code=400)
        eng = app.state.engine
        eng.refresh_last_price_from_public()
        out = eng.close_paper_position(tid)
        return JSONResponse(out, status_code=200 if out.get("ok") else 400)

    @app.post("/api/order/close")
    def api_order_close(body: dict):
        return _api_order_close_impl(body)

    @app.post("/api/order/close/")
    def api_order_close_trailing_slash(body: dict):
        return _api_order_close_impl(body)

    @app.post("/api/order-close")
    def api_order_close_hyphen(body: dict):
        """Alias: some proxies or mistaken configs break paths with extra slashes."""
        return _api_order_close_impl(body)

    @app.post("/api/order/manual")
    @app.post("/api/order/manual/")
    def api_order_manual(body: dict):
        eng = app.state.engine
        eng.refresh_last_price_from_public()
        symbol = str(body.get("symbol", eng.strategy_symbol()))
        market = str(body.get("market", eng.active_market()))
        side = str(body.get("side", "buy")).lower()
        quantity = _safe_float(body.get("quantity"), 0.0) or 0.0
        try:
            lev_raw = body.get("leverage")
            if lev_raw is None or lev_raw == "":
                leverage = eng.settings.default_leverage
            else:
                leverage = int(float(lev_raw))
        except (TypeError, ValueError):
            leverage = eng.settings.default_leverage
        tp_price = _safe_float(body.get("tp_price"))
        sl_price = _safe_float(body.get("sl_price"))
        try:
            out = eng.orders.place_manual(
                symbol=symbol,
                market=market,
                side=side,
                quantity=quantity,
                leverage=leverage,
                tp_price=tp_price,
                sl_price=sl_price,
                ecode=eng.active_ecode(),
            )
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        status = 200 if out.get("ok") else 400
        return JSONResponse(out, status_code=status)

    @app.post("/api/risk/update")
    def api_risk_update(body: dict):
        with Repository() as repo:
            for k, v in body.items():
                repo.set_config(f"risk:{k}", str(v))
        return {"ok": True}

    return app
