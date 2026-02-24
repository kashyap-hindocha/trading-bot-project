import sys
import os
import re
import json
sys.path.insert(0, '/home/ubuntu/trading-bot/bot')

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
import db

# Try to import strategy_manager, fallback if fails
try:
    import strategy_manager
    STRATEGY_MANAGER_LOADED = True
except Exception as e:
    import logging
    logging.error(f"Failed to import strategy_manager: {e}")
    STRATEGY_MANAGER_LOADED = False

from coindcx import CoinDCXREST, CoinDCXSocket
import threading
import time

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Confidence threshold for auto-enable/disable (75%)
CONFIDENCE_THRESHOLD = 75.0
BATCH_SIZE = 5
BATCH_DELAY_SEC = 2   # Seconds between each batch of 5 to avoid API exhaustion (~27 batches * 2s ≈ 54s for 135 pairs)
CYCLE_INTERVAL_SEC = 300  # 5 minutes — check enabled pairs confidence every 5 min

# Only one batch cycle at a time (prevents overlapping runs)
_batch_cycle_lock = threading.Lock()

# Batch checker state (for UI)
CONFIDENCE_HISTORY_MAX = 500  # Keep last N confidence results for history
_batch_state = {
    "current_batch": [],
    "current_batch_results": [],   # [{pair, readiness, bias, rsi, strategy_name}, ...] for the 5 being checked
    "batch_index": 0,
    "total_batches": 0,
    "total_pairs": 0,
    "current_strategy": None,      # Strategy key being used in this batch (for UI)
    "is_processing": False,
    "cycle_started_at": None,
    "next_run_at": None,
    "last_run_at": None,
    "last_error": None,
    "confidence_history": [],     # Last confidence check results: [{pair, readiness, strategy_name, checked_at}, ...]
}

app = Flask(__name__)
CORS(app)

db.init_db()


def _to_float(value):
    try:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            cleaned = cleaned.replace("₹", "").replace("INR", "").replace("USDT", "").strip()
            if cleaned == "":
                return None
            return float(cleaned)
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_balance(payload):
    keys = (
        "available_balance",
        "balance",
        "wallet_balance",
        "total_balance",
        "usdt_balance",
        "margin_balance",
    )

    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                numeric = _to_float(payload.get(key))
                if numeric is not None:
                    return numeric

        if payload.get("currency") == "USDT" or payload.get("asset") == "USDT":
            for key in keys:
                numeric = _to_float(payload.get(key))
                if numeric is not None:
                    return numeric

        for value in payload.values():
            numeric = _extract_balance(value)
            if numeric is not None:
                return numeric

    if isinstance(payload, list):
        for item in payload:
            numeric = _extract_balance(item)
            if numeric is not None:
                return numeric

    return None


def _resolve_inr_amount(pair: str, provided):
    if provided is not None:
        parsed = _to_float(provided)
        if parsed is not None:
            return parsed
    existing = db.get_pair_config(pair)
    if existing and existing.get("inr_amount") is not None:
        return existing.get("inr_amount")
    return 300.0


def _extract_balance_with_currency(payload):
    keys = (
        "available_balance",
        "availableBalance",
        "balance",
        "walletBalance",
        "wallet_balance",
        "currentValue",
        "current_value",
        "total_balance",
        "totalBalance",
        "margin_balance",
        "marginBalance",
        "usdt_balance",
        "usdtBalance",
        "inr_balance",
        "inrBalance",
    )

    candidates = []
    generic_candidates = []

    def walk(node, inherited_currency=None):
        if isinstance(node, dict):
            currency = (
                node.get("currency_short_name")  # CoinDCX futures uses this
                or node.get("currency")
                or node.get("asset")
                or node.get("asset_name")
                or node.get("assetName")
                or node.get("quote_currency")
                or node.get("quoteCurrency")
                or inherited_currency
            )
            currency = currency.upper() if isinstance(currency, str) else inherited_currency

            for key in keys:
                if key in node:
                    numeric = _to_float(node.get(key))
                    if numeric is not None:
                        candidates.append((currency, key, numeric))

            for key, raw_value in node.items():
                key_l = str(key).lower()
                numeric = _to_float(raw_value)
                if numeric is None:
                    continue

                include = (
                    "balance" in key_l
                    or "wallet" in key_l
                    or "equity" in key_l
                    or "value" in key_l
                    or "fund" in key_l
                )
                exclude = (
                    "pnl" in key_l
                    or "roi" in key_l
                    or "leverage" in key_l
                    or "rate" in key_l
                    or "price" in key_l
                    or "id" == key_l
                )

                if include and not exclude:
                    generic_candidates.append((currency, key, numeric))

            for value in node.values():
                walk(value, currency)

        elif isinstance(node, list):
            for item in node:
                walk(item, inherited_currency)

    walk(payload)

    if not candidates:
        candidates = generic_candidates

    if not candidates:
        return None, None

    key_priority = {
        "available_balance": 0,
        "wallet_balance": 1,
        "total_balance": 2,
        "balance": 3,
        "margin_balance": 4,
        "inr_balance": 5,
        "usdt_balance": 6,
        "availableBalance": 0,
        "walletBalance": 1,
        "totalBalance": 2,
        "marginBalance": 4,
        "inrBalance": 5,
        "usdtBalance": 6,
        "currentValue": 7,
        "current_value": 7,
    }

    def choose(cands):
        non_zero = [c for c in cands if c[2] != 0]
        pool = non_zero if non_zero else cands
        prioritized = [c for c in pool if c[1] in key_priority]
        if prioritized:
            return min(prioritized, key=lambda c: key_priority.get(c[1], 99))
        return max(pool, key=lambda c: abs(c[2]))

    inr_candidates = [c for c in candidates if c[0] == "INR"]
    if inr_candidates:
        currency, _, value = choose(inr_candidates)
        return value, currency

    usdt_candidates = [c for c in candidates if c[0] == "USDT"]
    if usdt_candidates:
        currency, _, value = choose(usdt_candidates)
        return value, currency

    currency, _, value = choose(candidates)
    return value, currency


def _is_not_found_payload(payload):
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status", "")).lower()
    message = str(payload.get("message", "")).lower()
    code = str(payload.get("code", ""))
    return status == "error" and ("not_found" in message or code == "404")


def _fetch_wallet_payload(key, secret, debug=False):
    import requests, hmac, hashlib, time, json

    # Official CoinDCX API endpoint from docs: https://docs.coindcx.com/#wallet-details
    # Returns array of wallets: [{"currency_short_name": "USDT", "balance": "123.45", ...}, ...]
    path = "/exchange/v1/derivatives/futures/wallets"

    try:
        # Create signature
        body = {"timestamp": int(time.time() * 1000)}
        sig = hmac.new(
            secret.encode(),
            json.dumps(body, separators=(",", ":")).encode(),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": key,
            "X-AUTH-SIGNATURE": sig,
        }

        # GET request as per official docs
        # IMPORTANT: Send the exact JSON string that was signed (use data= not json=)
        json_body = json.dumps(body, separators=(",", ":"))
        resp = requests.get(
            f"https://api.coindcx.com{path}",
            headers=headers,
            data=json_body,
            timeout=5,
        )
        
        if 200 <= resp.status_code < 300:
            payload = resp.json()
            if debug:
                return {"payload": payload, "status": resp.status_code}
            return payload
        else:
            if debug:
                return {"error": f"HTTP {resp.status_code}", "response": resp.text[:200]}
            return None
            
    except Exception as e:
        if debug:
            return {"error": str(e)}
        return None


def _get_real_balance():
    balance = 0.0
    balance_currency = "INR"
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key = os.getenv("COINDCX_API_KEY")
        secret = os.getenv("COINDCX_API_SECRET")

        if key and secret:
            client = CoinDCXREST(key, secret)
            payload = client.get_wallet()
            if payload:
                bal, curr = _extract_balance_with_currency(payload)
                if bal is not None:
                    balance = bal
                if curr is not None:
                    balance_currency = curr
    except Exception:
        pass

    try:
        if balance == 0.0:
            snapshots = db.get_equity_history(limit=200)
            if snapshots and len(snapshots) > 0:
                last_bal = _to_float(snapshots[-1].get("balance"))
                if last_bal:
                    balance = last_bal
    except Exception:
        pass

    return balance, balance_currency


@app.route("/api/status")
def status():
    balance, balance_currency = _get_real_balance()

    try:
        open_trades = db.get_open_trades()
        num_trades = len(open_trades)
    except Exception:
        num_trades = 0

    return jsonify({
        "bot_running": True,
        "balance": balance,
        "balance_currency": balance_currency,
        "open_trades": num_trades,
        "mode": db.get_trading_mode(),
        "paper_balance": db.get_paper_wallet_balance(),
    })


@app.route("/api/positions")
def positions():
    try:
        return jsonify(db.get_open_trades())
    except Exception as e:
        app.logger.error(f"Error fetching positions: {e}")
        return jsonify([])


@app.route("/api/trades")
def trades():
    try:
        return jsonify(db.get_all_trades(limit=100))
    except Exception as e:
        app.logger.error(f"Error fetching trades: {e}")
        return jsonify([])


@app.route("/api/stats")
def stats():
    try:
        return jsonify(db.get_trade_stats())
    except Exception as e:
        app.logger.error(f"Error fetching stats: {e}")
        return jsonify({
            "total": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_pnl": 0.0
        })


@app.route("/api/paper/stats")
def paper_stats():
    try:
        return jsonify(db.get_paper_trade_stats())
    except Exception as e:
        app.logger.error(f"Error fetching paper stats: {e}")
        return jsonify({
            "total": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_pnl": 0.0
        })


@app.route("/api/equity")
def equity():
    try:
        return jsonify(db.get_equity_history(limit=200))
    except Exception as e:
        app.logger.error(f"Error fetching equity: {e}")
        return jsonify([])


@app.route("/api/paper/equity")
def paper_equity():
    try:
        return jsonify(db.get_paper_equity_history(limit=200))
    except Exception as e:
        app.logger.error(f"Error fetching paper equity: {e}")
        return jsonify([])


@app.route("/api/logs")
def logs():
    try:
        logs_data = db.get_recent_logs(limit=50)
        # Convert UTC times to IST
        for log in logs_data:
            if log.get('created_at'):
                try:
                    # Parse UTC time and convert to IST
                    utc_time = datetime.fromisoformat(log['created_at'].replace('Z', '+00:00'))
                    ist_time = utc_time.astimezone(IST)
                    log['created_at'] = ist_time.isoformat()
                except Exception:
                    pass  # Keep original time if conversion fails
        return jsonify(logs_data)
    except Exception as e:
        app.logger.error(f"Error fetching logs: {e}")
        return jsonify([])


@app.route("/api/paper/trades")
def paper_trades():
    try:
        return jsonify(db.get_all_paper_trades(limit=100))
    except Exception as e:
        app.logger.error(f"Error fetching paper trades: {e}")
        return jsonify([])


@app.route("/api/trades/open")
def open_trades():
    """Get all currently open trades with details for multi-trade view"""
    try:
        trades = db.get_open_trades()
        if not trades:
            return jsonify([])
        
        # Enhance with pair info and confidence details
        enhanced = []
        for trade in trades:
            enhanced.append({
                "id": trade.get("id"),
                "position_id": trade.get("position_id"),
                "pair": trade.get("pair"),
                "side": trade.get("side"),
                "entry_price": trade.get("entry_price"),
                "quantity": trade.get("quantity"),
                "leverage": trade.get("leverage"),
                "tp_price": trade.get("tp_price"),
                "sl_price": trade.get("sl_price"),
                "opened_at": trade.get("opened_at"),
                "status": trade.get("status", "open"),
                "strategy_name": trade.get("strategy_name"),
            })
        return jsonify(enhanced)
    except Exception as e:
        app.logger.error(f"Error fetching open trades: {e}")
        return jsonify([])


@app.route("/api/paper/trades/open")
def open_paper_trades():
    """Get all currently open paper trades with details for multi-trade view"""
    try:
        trades = db.get_open_paper_trades()
        if not trades:
            return jsonify([])
        
        # Enhance with pair info and confidence details
        enhanced = []
        for trade in trades:
            enhanced.append({
                "id": trade.get("id"),
                "position_id": trade.get("position_id"),
                "pair": trade.get("pair"),
                "side": trade.get("side"),
                "entry_price": trade.get("entry_price"),
                "quantity": trade.get("quantity"),
                "leverage": trade.get("leverage"),
                "tp_price": trade.get("tp_price"),
                "sl_price": trade.get("sl_price"),
                "opened_at": trade.get("opened_at"),
                "status": trade.get("status", "open"),
                "strategy_name": trade.get("strategy_name"),
            })
        return jsonify(enhanced)
    except Exception as e:
        app.logger.error(f"Error fetching open paper trades: {e}")
        return jsonify([])


@app.route("/api/mode", methods=["GET", "POST"])
def trading_mode():
    if request.method == "GET":
        return jsonify({"mode": db.get_trading_mode()})

    data = request.get_json() or {}
    mode = str(data.get("mode", "REAL")).upper()
    if mode not in ("REAL", "PAPER"):
        return jsonify({"error": "mode must be REAL or PAPER"}), 400

    if mode == "PAPER":
        real_balance, _ = _get_real_balance()
        db.init_paper_wallet_if_missing(real_balance)

    db.set_trading_mode(mode)
    db.log_event("INFO", f"Trading mode set to {mode}")
    return jsonify({"success": True, "mode": mode})


@app.route("/api/strategies", methods=["GET", "POST"])
def strategies():
    if request.method == "GET":
        try:
            batch_mode = db.get_batch_strategy_mode() or "enhanced_v2"
            if not STRATEGY_MANAGER_LOADED:
                return jsonify({
                    "strategies": [],
                    "active": None,
                    "batch_mode": batch_mode,
                    "error": "Strategy manager not loaded"
                }), 500

            available_strategies = strategy_manager.strategy_manager.get_available_strategies()
            active_strategy = strategy_manager.strategy_manager.get_active_strategy_name()
            result = {
                "strategies": [{"name": s["name"], "displayName": s.get("display_name", s["name"]), "description": s["description"]} for s in available_strategies],
                "active": active_strategy,
                "batch_mode": batch_mode,
            }
            return jsonify(result)
        except Exception as e:
            try:
                batch_mode = db.get_batch_strategy_mode() or "enhanced_v2"
            except Exception:
                batch_mode = "enhanced_v2"
            return jsonify({
                "strategies": [],
                "active": None,
                "batch_mode": batch_mode,
                "error": str(e)
            }), 500

    if not STRATEGY_MANAGER_LOADED:
        return jsonify({"error": "Strategy manager not loaded"}), 500

    data = request.get_json() or {}
    strategy_name = str(data.get("strategy", "")).strip()
    
    if not strategy_name:
        return jsonify({"error": "strategy name is required"}), 400

    try:
        if strategy_name == "auto":
            db.set_batch_strategy_mode("auto")
            db.log_event("INFO", "Batch checker mode set to Auto (cycle all 3 strategies)")
            return jsonify({"success": True, "strategy": "auto", "batch_mode": "auto"})
        if strategy_name in getattr(strategy_manager.strategy_manager, "strategies", {}):
            strategy_manager.strategy_manager.set_active_strategy(strategy_name)
            db.set_batch_strategy_mode(strategy_name)
            db.log_event("INFO", f"Active strategy and batch mode set to {strategy_name}")
            return jsonify({"success": True, "strategy": strategy_name, "batch_mode": strategy_name})
        return jsonify({"error": f"Unknown strategy: {strategy_name}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/paper/balance")
def paper_balance():
    return jsonify({"balance": db.get_paper_wallet_balance()})


@app.route("/api/paper/reset", methods=["POST"])
def paper_reset():
    try:
        real_balance, _ = _get_real_balance()
        db.set_paper_wallet_balance(real_balance)
        db.log_event("INFO", f"Paper balance reset to {real_balance}")
        return jsonify({"success": True, "balance": real_balance})
    except Exception as e:
        import traceback
        app.logger.error(f"Paper reset failed: {e}")
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500




def _ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes, period):
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _compute_readiness(closes):
    """
    Compute readiness as PROXIMITY to trade conditions.
    Shows how close we are to executing (90% = ready to execute).
    """
    active_strategy = strategy_manager.strategy_manager.get_active_strategy()
    if not active_strategy:
        return None
    
    config = active_strategy.get_config()
    ema_fast_series = _ema(closes, config["ema_fast"])
    ema_slow_series = _ema(closes, config["ema_slow"])
    if not ema_fast_series or not ema_slow_series:
        return None

    ema_fast = ema_fast_series[-1]
    ema_slow = ema_slow_series[-1]
    rsi = _rsi(closes, config["rsi_period"])
    overbought = config["rsi_overbought"]
    oversold = config["rsi_oversold"]

    price = closes[-1] if closes else 0
    gap = abs(ema_fast - ema_slow)
    gap_pct = (gap / price) if price else 0
    gap_max = 0.003  # Max gap % for scoring

    def score_gap(local_gap):
        """Score how close EMAs are (closer = higher score)"""
        if local_gap >= gap_max:
            return 0.0
        return max(0.0, 1 - (local_gap / gap_max))

    # EMA proximity scores (higher when EMAs are close)
    ema_buy_score = score_gap(gap_pct) if ema_fast <= ema_slow else 0.0
    ema_sell_score = score_gap(gap_pct) if ema_fast >= ema_slow else 0.0

    # RSI alignment scores
    rsi_band = 20.0
    rsi_buy_score = 1.0 if rsi <= oversold else max(0.0, 1 - ((rsi - oversold) / rsi_band))
    rsi_sell_score = 1.0 if rsi >= overbought else max(0.0, 1 - ((overbought - rsi) / rsi_band))

    # Combine scores (60% EMA proximity, 40% RSI alignment)
    buy_readiness = (ema_buy_score * 0.6 + rsi_buy_score * 0.4) * 100
    sell_readiness = (ema_sell_score * 0.6 + rsi_sell_score * 0.4) * 100

    readiness = round(max(buy_readiness, sell_readiness), 1)
    bias = "BUY" if buy_readiness >= sell_readiness else "SELL"

    return {
        "readiness": readiness,
        "bias": bias,
        "ema_gap_pct": round(gap_pct * 100, 3),
        "rsi": rsi,
    }


def _get_coindcx_client():
    """Get CoinDCX client (authenticated if available, else public)."""
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key = os.getenv("COINDCX_API_KEY")
        secret = os.getenv("COINDCX_API_SECRET")
        if key and secret:
            return CoinDCXREST(key, secret)
    except Exception:
        pass
    return CoinDCXREST("", "")


def _seed_pair_config_if_empty():
    """Seed pair_config from CoinDCX if empty."""
    configs = db.get_all_pair_configs()
    if configs:
        return
    try:
        client = _get_coindcx_client()
        instruments = client.get_active_instruments()
        if not isinstance(instruments, list):
            return
        for inst in instruments:
            symbol = inst if isinstance(inst, str) else (inst.get("symbol") or inst.get("pair", ""))
            if symbol and "USDT" in symbol:
                try:
                    db.upsert_pair_config(symbol, 0, 5, 0.001, 300.0)
                except Exception:
                    pass
        app.logger.info("Seeded pair_config from CoinDCX")
    except Exception as e:
        app.logger.warning(f"Could not seed pair_config: {e}")


def _batch_compute_readiness(pairs, client, interval):
    """Compute readiness for exactly one batch of up to 5 pairs. Never more than BATCH_SIZE."""
    # Enforce exactly 5 (or fewer for last batch): take first BATCH_SIZE only
    batch_list = (list(pairs)[:BATCH_SIZE]) if pairs else []
    results = []
    for pair in batch_list:
        try:
            candles = client.get_candles(pair, interval, limit=150)
            closes = [c.get("close") for c in candles if c.get("close") is not None]
            r = _compute_readiness(closes)
            if r is None:
                results.append({"pair": pair, "readiness": 0.0, "bias": None, "ema_gap_pct": None, "rsi": None})
            else:
                results.append({"pair": pair, **r})
        except Exception as e:
            app.logger.warning(f"Readiness failed for {pair}: {e}")
            results.append({"pair": pair, "readiness": 0.0, "bias": None, "ema_gap_pct": None, "rsi": None})
    return results


def _get_strategy_instance(strategy_key):
    """Return a strategy instance by key (e.g. enhanced_v2, bollinger_rsi, breakout_vol)."""
    if not STRATEGY_MANAGER_LOADED:
        return None
    try:
        strategies = getattr(strategy_manager.strategy_manager, "strategies", {})
        strategy_class = strategies.get(strategy_key)
        if strategy_class:
            return strategy_class()
    except Exception as e:
        app.logger.warning(f"Could not get strategy {strategy_key}: {e}")
    return None


def _batch_compute_readiness_with_strategy(pairs, client, interval, strategy_instance, strategy_key):
    """
    Compute confidence (readiness) for exactly one batch of up to 5 pairs using the given strategy.
    Returns list of {pair, readiness (confidence %), strategy_name, bias, ...}.
    """
    batch_list = (list(pairs)[:BATCH_SIZE]) if pairs else []
    results = []
    strategy_name = strategy_instance.get_name() if strategy_instance else (strategy_key or "")
    for pair in batch_list:
        try:
            candles = client.get_candles(pair, interval, limit=200)
            if not candles or len(candles) < 50:
                results.append({
                    "pair": pair, "readiness": 0.0, "bias": None, "strategy_name": strategy_name,
                    "ema_gap_pct": None, "rsi": None,
                })
                continue
            # Normalize candle dicts (ensure close, high, low, volume, etc.)
            candles = [
                {"open": c.get("open"), "high": c.get("high"), "low": c.get("low"),
                 "close": c.get("close"), "volume": c.get("volume", 0), "time": c.get("time")}
                for c in candles
            ]
            ev = strategy_instance.evaluate(candles, return_confidence=True)
            if ev and isinstance(ev, dict):
                confidence = float(ev.get("confidence", 0))
                signal = ev.get("signal")
                bias = "BUY" if signal == "LONG" else ("SELL" if signal == "SHORT" else None)
                results.append({
                    "pair": pair, "readiness": round(confidence, 1), "bias": bias,
                    "strategy_name": strategy_name, "strategy_key": strategy_key,
                    "ema_gap_pct": None, "rsi": None,
                })
            else:
                results.append({
                    "pair": pair, "readiness": 0.0, "bias": None, "strategy_name": strategy_name,
                    "ema_gap_pct": None, "rsi": None,
                })
        except Exception as e:
            app.logger.warning(f"Strategy readiness failed for {pair} ({strategy_key}): {e}")
            results.append({
                "pair": pair, "readiness": 0.0, "bias": None, "strategy_name": strategy_name,
                "ema_gap_pct": None, "rsi": None,
            })
    return results


def _run_batch_cycle():
    """Run one full confidence-check cycle using strategy-based confidence.
    Batch mode 'auto': iterate strategies [enhanced_v2, bollinger_rsi, breakout_vol], for each
    strategy run through ALL pairs in batches of 5. Single-strategy mode: use only that strategy.
    Enable pair when confidence > 75%; store enabled_by_strategy and enabled_at_confidence.
    """
    global _batch_state
    if not _batch_cycle_lock.acquire(blocking=False):
        app.logger.info("Batch cycle already running, skipping")
        return
    try:
        if not STRATEGY_MANAGER_LOADED:
            _batch_state["last_error"] = "Strategy manager not loaded"
            return

        _batch_state["is_processing"] = True
        _batch_state["cycle_started_at"] = datetime.now(IST).isoformat()
        _batch_state["last_error"] = None

        try:
            _seed_pair_config_if_empty()
            all_configs = db.get_all_pair_configs()
            if not all_configs:
                _batch_state["is_processing"] = False
                _batch_state["last_run_at"] = datetime.now(IST).isoformat()
                return

            all_pairs = [c["pair"] for c in all_configs]
            total_pairs = len(all_pairs)
            total_batches_per_strategy = (total_pairs + BATCH_SIZE - 1) // BATCH_SIZE if total_pairs else 0
            client = _get_coindcx_client()
            # Map pair -> strategy key that enabled it; only disable when THAT strategy says < 75%
            auto_enabled_list = db.get_auto_enabled_pairs()
            pair_enabled_by = {c["pair"]: c.get("enabled_by_strategy") for c in auto_enabled_list}

            batch_mode = db.get_batch_strategy_mode() or "enhanced_v2"
            if batch_mode == "auto":
                strategy_order = ["enhanced_v2", "bollinger_rsi", "breakout_vol"]
                strategies_to_run = [
                    (key, _get_strategy_instance(key)) for key in strategy_order
                    if _get_strategy_instance(key) is not None
                ]
                if not strategies_to_run:
                    _batch_state["last_error"] = "No strategies available for auto mode"
                    return
                total_batches = total_batches_per_strategy * len(strategies_to_run)
                batch_counter = 0
                for strategy_key, strategy_instance in strategies_to_run:
                    interval = strategy_instance.get_config().get("interval", "5m")
                    _batch_state["current_strategy"] = strategy_key
                    for batch_start in range(0, total_pairs, BATCH_SIZE):
                        batch = all_pairs[batch_start : batch_start + BATCH_SIZE]
                        if len(batch) > BATCH_SIZE:
                            batch = batch[:BATCH_SIZE]
                        batch_index_1based = (batch_start // BATCH_SIZE) + 1
                        batch_counter += 1
                        _batch_state["current_batch"] = list(batch)
                        _batch_state["batch_index"] = batch_counter
                        _batch_state["total_batches"] = total_batches
                        _batch_state["total_pairs"] = total_pairs
                        results = _batch_compute_readiness_with_strategy(
                            batch, client, interval, strategy_instance, strategy_key
                        )
                        _batch_state["current_batch_results"] = list(results)
                        now_iso = datetime.now(IST).isoformat()
                        for r in results:
                            entry = {**r, "checked_at": now_iso}
                            _batch_state["confidence_history"].append(entry)
                        _batch_state["confidence_history"] = _batch_state["confidence_history"][-CONFIDENCE_HISTORY_MAX:]
                        for r in results:
                            pair = r.get("pair", "")
                            readiness = r.get("readiness", 0)
                            strat_key = r.get("strategy_key", strategy_key)
                            if readiness > CONFIDENCE_THRESHOLD:
                                db.update_pair_auto_status(pair, 1, 1, enabled_by_strategy=strat_key, enabled_at_confidence=readiness)
                                db.log_event("INFO", f"Auto-enabled {pair} ({strat_key} {readiness:.1f}% > {CONFIDENCE_THRESHOLD}%)")
                                pair_enabled_by[pair] = strat_key
                            elif pair_enabled_by.get(pair) == strat_key and readiness < CONFIDENCE_THRESHOLD:
                                db.update_pair_auto_status(pair, 0, 0, enabled_by_strategy=None, enabled_at_confidence=None)
                                db.log_event("INFO", f"Auto-disabled {pair} ({strat_key} {readiness:.1f}% < {CONFIDENCE_THRESHOLD}%, was enabled by this strategy)")
                                del pair_enabled_by[pair]
                        if batch_start + BATCH_SIZE < total_pairs or strategy_key != strategies_to_run[-1][0]:
                            time.sleep(BATCH_DELAY_SEC)
            else:
                strategy_instance = _get_strategy_instance(batch_mode)
                if not strategy_instance:
                    _batch_state["last_error"] = f"Strategy {batch_mode} not found"
                    return
                interval = strategy_instance.get_config().get("interval", "5m")
                total_batches = total_batches_per_strategy
                _batch_state["current_strategy"] = batch_mode
                for batch_start in range(0, total_pairs, BATCH_SIZE):
                    batch = all_pairs[batch_start : batch_start + BATCH_SIZE]
                    if len(batch) > BATCH_SIZE:
                        batch = batch[:BATCH_SIZE]
                    batch_index_1based = (batch_start // BATCH_SIZE) + 1
                    _batch_state["current_batch"] = list(batch)
                    _batch_state["batch_index"] = batch_index_1based
                    _batch_state["total_batches"] = total_batches
                    _batch_state["total_pairs"] = total_pairs
                    results = _batch_compute_readiness_with_strategy(
                        batch, client, interval, strategy_instance, batch_mode
                    )
                    _batch_state["current_batch_results"] = list(results)
                    now_iso = datetime.now(IST).isoformat()
                    for r in results:
                        entry = {**r, "checked_at": now_iso}
                        _batch_state["confidence_history"].append(entry)
                    _batch_state["confidence_history"] = _batch_state["confidence_history"][-CONFIDENCE_HISTORY_MAX:]
                    for r in results:
                        pair = r.get("pair", "")
                        readiness = r.get("readiness", 0)
                        if readiness > CONFIDENCE_THRESHOLD:
                            db.update_pair_auto_status(pair, 1, 1, enabled_by_strategy=batch_mode, enabled_at_confidence=readiness)
                            db.log_event("INFO", f"Auto-enabled {pair} ({batch_mode} {readiness:.1f}% > {CONFIDENCE_THRESHOLD}%)")
                            pair_enabled_by[pair] = batch_mode
                        elif pair_enabled_by.get(pair) == batch_mode and readiness < CONFIDENCE_THRESHOLD:
                            db.update_pair_auto_status(pair, 0, 0, enabled_by_strategy=None, enabled_at_confidence=None)
                            db.log_event("INFO", f"Auto-disabled {pair} ({batch_mode} {readiness:.1f}% < {CONFIDENCE_THRESHOLD}%)")
                            del pair_enabled_by[pair]
                    if batch_start + BATCH_SIZE < total_pairs:
                        time.sleep(BATCH_DELAY_SEC)

            _batch_state["current_batch"] = []
            _batch_state["current_batch_results"] = []
            _batch_state["batch_index"] = 0
            _batch_state["current_strategy"] = None
        except Exception as e:
            _batch_state["last_error"] = str(e)
            app.logger.error(f"Batch cycle error: {e}")
        finally:
            _batch_state["is_processing"] = False
            _batch_state["last_run_at"] = datetime.now(IST).isoformat()
    finally:
        _batch_cycle_lock.release()


def _batch_checker_loop():
    """Background thread: run full cycle then wait 5 min."""
    import time
    while True:
        try:
            _run_batch_cycle()
        except Exception as e:
            app.logger.error(f"Batch checker error: {e}")
            _batch_state["last_error"] = str(e)
        next_run = datetime.now(IST) + timedelta(seconds=CYCLE_INTERVAL_SEC)
        _batch_state["next_run_at"] = next_run.isoformat()
        _batch_state["seconds_until_next"] = CYCLE_INTERVAL_SEC
        time.sleep(CYCLE_INTERVAL_SEC)


def _start_batch_checker():
    """Start the batch checker background thread."""
    t = threading.Thread(target=_batch_checker_loop, daemon=True)
    t.start()
    app.logger.info("Batch confidence checker started (5 min cycle)")


@app.route("/api/signal/readiness")
def signal_readiness():
    try:
        pairs_raw = request.args.get("pairs", "")
        pairs = [p.strip() for p in pairs_raw.split(",") if p.strip()]
        if not pairs:
            return jsonify([])

        client = CoinDCXREST("", "")
        results = []
        active_strategy = strategy_manager.strategy_manager.get_active_strategy()
        interval = active_strategy.get_config().get("interval", "1m") if active_strategy else "1m"
        
        # Max 5 pairs per request to avoid API exhaustion and align with batch-of-5 checking
        for pair in pairs[:5]:
            try:
                candles = client.get_candles(pair, interval, limit=150)
                closes = [c.get("close") for c in candles if c.get("close") is not None]
                readiness = _compute_readiness(closes)
                # _compute_readiness may return None if not enough data; treat that as 0%
                if readiness is None:
                    results.append({
                        "pair": pair,
                        "readiness": 0.0,
                        "bias": None,
                        "ema_gap_pct": None,
                        "rsi": None,
                    })
                else:
                    # Even readiness 0.0 is meaningful; don't filter it out
                    results.append({"pair": pair, **readiness})
            except Exception as e:
                app.logger.warning(f"Readiness failed for {pair}: {e}")
        return jsonify(results)
    except Exception as e:
        import traceback
        app.logger.error(f"Readiness endpoint failed: {e}")
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/candles")
def get_candles():
    """Fetch OHLCV candlestick data for a pair."""
    try:
        pair = request.args.get("pair", "B-BTC_USDT")
        interval = request.args.get("interval", "5m")
        limit = int(request.args.get("limit", 50))
        # Cap at 80 to match UI chart needs and save data
        if limit > 80:
            limit = 80
        
        client = CoinDCXREST("", "")
        candles = client.get_candles(pair, interval, limit=limit)
        
        if not candles:
            return jsonify([])
        
        # Format for chart
        formatted = []
        for c in candles:
            try:
                formatted.append({
                    "timestamp": c.get("time", ""),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "volume": float(c.get("volume", 0))
                })
            except Exception:
                pass
        
        return jsonify(formatted)
    except Exception as e:
        app.logger.error(f"Candles fetch failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.errorhandler(Exception)
def handle_api_error(error):
    try:
        if request.path.startswith("/api/"):
            import traceback
            return jsonify({"error": str(error), "traceback": traceback.format_exc()}), 500
    except Exception:
        pass
    raise error


@app.route("/api/debug/wallet")
def debug_wallet():
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key = os.getenv("COINDCX_API_KEY")
        secret = os.getenv("COINDCX_API_SECRET")
        
        if not key or not secret:
            return jsonify({"error": "API credentials not configured"}), 500
        
        client = CoinDCXREST(key, secret)
        
        # Try positions endpoint - this likely contains margin/balance
        positions_data = None
        try:
            positions_data = client.get_positions()
        except Exception as e:
            positions_data = {"error": str(e)}
        
        # Try orders endpoint
        orders_data = None
        try:
            orders_data = client.get_open_orders()
        except Exception as e:
            orders_data = {"error": str(e)}
        
        # Try wallet (we know it fails)
        wallet_data = None
        try:
            wallet_data = client.get_wallet()
        except Exception as e:
            wallet_data = {"error": str(e)}
        
        return jsonify({
            "positions": positions_data,
            "orders": orders_data,
            "wallet": wallet_data,
            "note": "Check positions for margin/equity/balance fields"
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    import subprocess
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "/usr/bin/systemctl", "start", "bot"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            db.log_event("INFO", "Bot started manually from dashboard")
            # Trigger one batch cycle so pairs get re-evaluated (batch-of-5) after start
            try:
                t = threading.Thread(target=_run_batch_cycle, daemon=True)
                t.start()
            except Exception as e:
                app.logger.warning(f"Batch trigger on start: {e}")
            return jsonify({"success": True, "message": "Bot started; confidence check triggered"})
        return jsonify({"success": False, "message": result.stderr or "Failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    import subprocess
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "/usr/bin/systemctl", "stop", "bot"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            # Disable all pairs when bot is turned off so they are re-evaluated on next start
            try:
                all_configs = db.get_all_pair_configs()
                for cfg in all_configs:
                    if cfg.get("enabled") == 1:
                        db.upsert_pair_config(
                            cfg["pair"], 0,
                            cfg.get("leverage", 5),
                            cfg.get("quantity", 0.001),
                            cfg.get("inr_amount", 300.0)
                        )
                db.log_event("INFO", "All pairs disabled on bot stop")
            except Exception as e:
                app.logger.warning(f"Disable-all on stop: {e}")
            db.log_event("WARNING", "Bot stopped manually from dashboard")
            return jsonify({"success": True, "message": "Bot stopped; all pairs disabled"})
        return jsonify({"success": False, "message": result.stderr or "Failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/bot/status")
def bot_status():
    import subprocess
    try:
        # Try user first, then system
        for cmd in [["systemctl", "--user", "is-active", "bot.service"], ["/usr/bin/systemctl", "is-active", "bot"]]:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip() == "active":
                    return jsonify({"running": True})
            except Exception:
                continue
        return jsonify({"running": False})
    except Exception:
        return jsonify({"running": False})


@app.route("/api/paper/diagnostic")
def paper_diagnostic():
    """Help debug why paper trades might not run: mode, wallet, enabled pairs, checklist."""
    try:
        mode = db.get_trading_mode()
        paper_balance = db.get_paper_wallet_balance()
        enabled = db.get_enabled_pairs()
        enabled_pairs = [p.get("pair") for p in enabled if p.get("pair")]
        open_paper = db.get_open_paper_trades()
        checks = []
        if mode != "PAPER":
            checks.append("Mode is not PAPER; switch to PAPER in dashboard to run paper trades.")
        if paper_balance is None or (isinstance(paper_balance, (int, float)) and paper_balance <= 0):
            checks.append("Paper wallet not initialized or zero. Switch to PAPER mode once in dashboard to seed it.")
        if not enabled_pairs:
            checks.append("No pairs enabled. Batch checker enables pairs at >=75%% confidence.")
        if len(open_paper) >= 3:
            checks.append("Already 3 open paper trades (max). Close one to allow new entries.")
        if not checks:
            checks.append("Config looks OK. Trades run on 5m candle close. Check bot logs for 'Closed candle', 'Signal', 'PAPER entry' or 'Signal rejected'.")
        return jsonify({
            "mode": mode,
            "paper_balance": paper_balance,
            "enabled_pairs_count": len(enabled_pairs),
            "enabled_pairs": enabled_pairs[:20],
            "open_paper_count": len(open_paper),
            "checks": checks,
        })
    except Exception as e:
        app.logger.error(f"Paper diagnostic: {e}")
        return jsonify({"error": str(e)}), 500


TAKER_FEE_RATE = 0.0005  # 0.05% for paper trade fee simulation


@app.route("/api/paper/execute_trade", methods=["POST"])
def paper_execute_trade():
    """Manually execute a paper trade for an enabled pair only. Use to test API/strategy and see errors."""
    try:
        data = request.get_json() or {}
        pair = (data.get("pair") or "").strip()
        if not pair:
            return jsonify({"success": False, "error": "Missing 'pair' (e.g. B-OP_USDT)"}), 400

        enabled_pairs = db.get_enabled_pairs()
        enabled_pair_names = {p.get("pair") for p in enabled_pairs if p.get("pair")}
        if pair not in enabled_pair_names:
            return jsonify({"success": False, "error": f"Pair {pair} is not enabled. Enable it first."}), 400

        mode = db.get_trading_mode()
        if mode != "PAPER":
            return jsonify({"success": False, "error": "Manual execute is paper-only. Switch mode to PAPER."}), 400

        pair_config = next((c for c in enabled_pairs if c.get("pair") == pair), None)
        if not pair_config:
            return jsonify({"success": False, "error": "Pair config not found"}), 400

        client = _get_coindcx_client()
        candles = client.get_candles(pair, "5m", limit=200)
        if not candles or len(candles) < 50:
            return jsonify({"success": False, "error": f"Not enough candles for {pair} (need ≥50)"}), 400

        candles_norm = [
            {"open": c.get("open", c.get("o")), "high": c.get("high", c.get("h")), "low": c.get("low", c.get("l")),
             "close": c.get("close", c.get("c")), "volume": c.get("volume", c.get("v", 0)), "time": c.get("time", c.get("t"))}
            for c in candles
        ]
        current_price = float(candles[-1].get("close", candles[-1].get("c", 0)))
        if not current_price:
            return jsonify({"success": False, "error": "Could not get current price"}), 400

        enabled_by_strategy = pair_config.get("enabled_by_strategy")
        strat_instance = _get_strategy_instance(enabled_by_strategy) if enabled_by_strategy else None
        if not strat_instance and STRATEGY_MANAGER_LOADED:
            strat_instance = strategy_manager.strategy_manager.get_active_strategy()
        if not strat_instance:
            return jsonify({"success": False, "error": "No strategy available for this pair"}), 500

        ev = strat_instance.evaluate(candles_norm, return_confidence=True)
        if isinstance(ev, dict):
            signal = ev.get("signal")
            confidence = float(ev.get("confidence", 0))
            atr = float(ev.get("atr", 0))
            position_size = float(ev.get("position_size", 0))
            trailing_stop = float(ev.get("trailing_stop", 0))
        else:
            signal = ev
            confidence = atr = position_size = trailing_stop = 0.0

        if not signal:
            return jsonify({
                "success": False,
                "message": "No signal from strategy",
                "confidence": round(confidence, 1),
            }), 200

        leverage = int(pair_config.get("leverage", 5))
        quantity = float(pair_config.get("quantity", 0.001))
        inr_amount = pair_config.get("inr_amount")
        if inr_amount is not None and inr_amount != "":
            inr_amount = float(inr_amount)
        else:
            inr_amount = None
        if inr_amount and current_price > 0:
            rate = client.get_inr_usdt_rate()
            if rate and rate > 0:
                usdt_margin = inr_amount / rate
                quantity = (usdt_margin * leverage) / current_price

        wallet_balance = db.get_paper_wallet_balance()
        if wallet_balance is None or wallet_balance <= 0:
            return jsonify({"success": False, "error": "Paper wallet not initialized. Switch to PAPER mode once."}), 400
        entry_fee = current_price * quantity * TAKER_FEE_RATE
        if entry_fee > wallet_balance:
            return jsonify({"success": False, "error": "PAPER wallet insufficient for fee"}), 400

        tp_price, sl_price = strat_instance.calculate_tp_sl(current_price, signal, atr) if strat_instance else (0, 0)
        side = "buy" if signal == "LONG" else "sell"
        order_id = f"PAPER-MANUAL-{int(time.time() * 1000)}"
        position_id = f"PAPER-POS-{order_id}"
        strategy_key = (pair_config.get("enabled_by_strategy") or (strategy_manager.strategy_manager.get_active_strategy_name() if STRATEGY_MANAGER_LOADED else "")) or "enhanced_v2"

        db.set_paper_wallet_balance(wallet_balance - entry_fee)
        db.insert_paper_trade(
            pair=pair,
            side=side,
            entry_price=current_price,
            quantity=quantity,
            leverage=leverage,
            tp_price=tp_price,
            sl_price=sl_price,
            fee_paid=entry_fee,
            order_id=order_id,
            position_id=position_id,
            strategy_name=strategy_key,
            strategy_note=f"Manual execute | {signal} | Confidence: {confidence:.1f}%",
            confidence=confidence,
            atr=atr,
            position_size=position_size,
            trailing_stop=trailing_stop,
        )
        db.upsert_pair_execution_status(pair, last_signal=signal, last_confidence=confidence, last_error=None)
        db.log_event("INFO", f"Manual PAPER entry {pair} {signal} qty={quantity} lev={leverage} | Confidence: {confidence:.1f}%")

        return jsonify({
            "success": True,
            "message": f"PAPER {signal} {pair} @ {current_price}",
            "order_id": order_id,
            "position_id": position_id,
            "side": side,
            "quantity": quantity,
            "leverage": leverage,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "confidence": round(confidence, 1),
        })
    except Exception as e:
        app.logger.exception(f"Manual execute failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Pair Management ──────────────────────────
@app.route("/api/pairs/available")
def pairs_available():
    """Get all available trading pairs from CoinDCX."""
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key = os.getenv("COINDCX_API_KEY")
        secret = os.getenv("COINDCX_API_SECRET")
        
        if not key or not secret:
            return jsonify({"error": "API credentials not configured"}), 500
        
        client = CoinDCXREST(key, secret)
        instruments = client.get_active_instruments()
        
        # Filter for futures pairs and format
        # instruments is a list of strings like ["B-BTC_USDT", "B-ETH_USDT", ...]
        pairs = []
        for inst in instruments:
            # Handle both string format and dict format
            if isinstance(inst, str):
                symbol = inst
            elif isinstance(inst, dict):
                symbol = inst.get("symbol", inst.get("pair", ""))
            else:
                continue
                
            if symbol and "USDT" in symbol:  # Focus on USDT pairs
                base = symbol.replace("B-", "").replace("_USDT", "")
                pairs.append({
                    "pair": symbol,
                    "base": base,
                    "quote": "USDT"
                })
        
        return jsonify(pairs)
    except Exception as e:
        app.logger.error(f"Error fetching pairs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pairs/config")
def pairs_config():
    """Get all pair configurations."""
    try:
        configs = db.get_all_pair_configs()
        return jsonify(configs)
    except Exception as e:
        app.logger.error(f"Error fetching pair configs: {e}")
        return jsonify([])


@app.route("/api/pairs/config/update", methods=["POST"])
def pairs_config_update():
    """Update pair configuration."""
    try:
        from flask import request
        data = request.get_json()
        
        pair = data.get("pair")
        enabled = int(data.get("enabled", 0))
        if not pair:
            return jsonify({"error": "Pair is required"}), 400

        leverage = int(data.get("leverage", 5))
        quantity = float(data.get("quantity", 0.001))
        inr_amount = _resolve_inr_amount(pair, data.get("inr_amount"))
        
        db.upsert_pair_config(pair, enabled, leverage, quantity, inr_amount)
        db.log_event("INFO", f"Updated config for {pair}: enabled={enabled}, leverage={leverage}, qty={quantity}, inr={inr_amount}")
        
        return jsonify({"success": True, "message": f"Updated {pair} configuration"})
    except Exception as e:
        app.logger.error(f"Error updating pair config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pairs/config/bulk", methods=["POST"])
def pairs_config_bulk():
    """Bulk update pair configurations."""
    try:
        from flask import request
        data = request.get_json()
        pairs = data.get("pairs", [])
        
        for pair_data in pairs:
            pair = pair_data.get("pair")
            enabled = int(pair_data.get("enabled", 0))
            leverage = int(pair_data.get("leverage", 5))
            quantity = float(pair_data.get("quantity", 0.001))
            inr_amount = _resolve_inr_amount(pair, pair_data.get("inr_amount"))
            
            if pair:
                db.upsert_pair_config(pair, enabled, leverage, quantity, inr_amount)
        
        db.log_event("INFO", f"Bulk updated {len(pairs)} pair configurations")
        return jsonify({"success": True, "message": f"Updated {len(pairs)} pairs"})
    except Exception as e:
        app.logger.error(f"Error bulk updating pairs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/batch/status")
def batch_status():
    """Get batch checker status for UI: current batch, is_processing, countdown, auto-enabled pairs."""
    try:
        auto_enabled = db.get_auto_enabled_pairs()
        # Enrich with confidence from pair_signals / readiness - we use last known from batch
        # For now return configs; UI can fetch readiness separately for bars
        now = datetime.now(IST)
        next_run = _batch_state.get("next_run_at")
        next_run_dt = datetime.fromisoformat(next_run) if next_run else None
        seconds_until_next = int((next_run_dt - now).total_seconds()) if next_run_dt and next_run_dt > now else CYCLE_INTERVAL_SEC

        return jsonify({
            "current_batch": _batch_state.get("current_batch", []),
            "current_batch_results": _batch_state.get("current_batch_results", []),
            "batch_index": _batch_state.get("batch_index", 0),
            "total_batches": _batch_state.get("total_batches", 0),
            "total_pairs": _batch_state.get("total_pairs", 0),
            "current_strategy": _batch_state.get("current_strategy"),
            "batch_strategy_mode": db.get_batch_strategy_mode(),
            "is_processing": _batch_state.get("is_processing", False),
            "cycle_started_at": _batch_state.get("cycle_started_at"),
            "next_run_at": _batch_state.get("next_run_at"),
            "seconds_until_next": max(0, seconds_until_next),
            "last_run_at": _batch_state.get("last_run_at"),
            "last_error": _batch_state.get("last_error"),
            "auto_enabled_pairs": [
                {
                    "pair": c["pair"],
                    "leverage": c.get("leverage", 5),
                    "quantity": c.get("quantity", 0.001),
                    "inr_amount": c.get("inr_amount", 300),
                    "enabled_by_strategy": c.get("enabled_by_strategy"),
                    "enabled_at_confidence": c.get("enabled_at_confidence"),
                }
                for c in auto_enabled
            ],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/batch/confidence_history")
def batch_confidence_history():
    """Paginated last confidence check results (15 per page). Updates when next iteration runs."""
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(50, max(1, int(request.args.get("per_page", 15))))
        history = list(_batch_state.get("confidence_history", []))
        total = len(history)
        # Newest last in list; show newest first in UI
        history_reversed = list(reversed(history))
        start = (page - 1) * per_page
        chunk = history_reversed[start : start + per_page]
        return jsonify({
            "items": chunk,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page if total else 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/batch/trigger", methods=["POST"])
def batch_trigger():
    """Run one confidence-check cycle now (e.g. after bot start)."""
    try:
        t = threading.Thread(target=_run_batch_cycle, daemon=True)
        t.start()
        return jsonify({"success": True, "message": "Confidence check cycle started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/batch/auto-enabled")
def batch_auto_enabled():
    """Get auto-enabled pairs with readiness/confidence for review panel."""
    try:
        pairs = db.get_auto_enabled_pairs()
        if not pairs:
            return jsonify([])

        interval = "1m"
        if STRATEGY_MANAGER_LOADED:
            try:
                active = strategy_manager.strategy_manager.get_active_strategy()
                if active:
                    interval = active.get_config().get("interval", "1m")
            except Exception:
                pass
        client = _get_coindcx_client()
        pair_names = [p["pair"] for p in pairs]
        results = _batch_compute_readiness(pair_names, client, interval)
        readiness_map = {r["pair"]: r for r in results}

        result = []
        for p in pairs:
            r = readiness_map.get(p["pair"], {})
            result.append({
                "pair": p["pair"],
                "readiness": r.get("readiness", 0),
                "bias": r.get("bias"),
                "rsi": r.get("rsi"),
                "ema_gap_pct": r.get("ema_gap_pct"),
                "leverage": p.get("leverage", 5),
                "quantity": p.get("quantity", 0.001),
                "inr_amount": p.get("inr_amount", 300),
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/pairs/config/disable_all", methods=["POST"])
def pairs_config_disable_all():
    """Disable all pairs at once."""
    try:
        all_configs = db.get_all_pair_configs()
        count = 0
        
        for cfg in all_configs:
            if cfg.get("enabled") == 1:
                db.upsert_pair_config(
                    cfg["pair"], 
                    0,  # disabled
                    cfg.get("leverage", 5),
                    cfg.get("quantity", 0.001),
                    cfg.get("inr_amount", 300.0)
                )
                count += 1
        
        db.log_event("INFO", f"Disabled all {count} enabled pairs")
        return jsonify({"success": True, "message": f"Disabled {count} pairs"})
    except Exception as e:
        app.logger.error(f"Error disabling all pairs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pairs/prices")
def pairs_prices():
    """Get current prices for all available pairs from latest signal data."""
    try:
        # Get prices from the most recent pair_signals calculation
        # This reuses the signal calculation which already fetches candles
        enabled_pairs = db.get_enabled_pairs()
        
        if not enabled_pairs:
            return jsonify({})
        
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key = os.getenv("COINDCX_API_KEY")
        secret = os.getenv("COINDCX_API_SECRET")
        
        # Use authenticated client for market data
        if key and secret:
            client = CoinDCXREST(key, secret)
        else:
            # Fallback to unauthenticated (may have limited access)
            client = CoinDCXREST("", "")
        
        prices = {}
        
        # Fetch prices for all enabled pairs
        for cfg in enabled_pairs[:20]:  # Limit to 20 pairs for speed
            pair = cfg.get("pair")
            if not pair:
                continue
                
            try:
                # Get latest 1-minute candle for current price
                candles = client.get_candles(pair, "1m", limit=1)
                if candles and len(candles) > 0:
                    prices[pair] = float(candles[-1].get("close", 0))
                    app.logger.debug(f"Price for {pair}: {prices[pair]}")
            except Exception as e:
                app.logger.warning(f"Failed to get price for {pair}: {e}")
                continue
        
        app.logger.info(f"Loaded prices for {len(prices)} pairs")
        return jsonify(prices)
    except Exception as e:
        app.logger.error(f"Error fetching pair prices: {e}")
        return jsonify({})


@app.route("/api/pairs/active")
def pairs_active():
    """Get currently active trading pairs with open positions."""
    try:
        mode = db.get_trading_mode()
        
        # Get all open trades grouped by pair
        if mode == "PAPER":
            all_trades = db.get_open_paper_trades()
        else:
            all_trades = db.get_open_trades()
        
        # Group by pair
        pairs_trading = {}
        for trade in all_trades:
            pair = trade.get("pair")
            if pair not in pairs_trading:
                pairs_trading[pair] = {
                    "pair": pair,
                    "open_positions": 0,
                    "total_confidence": 0.0,
                    "avg_confidence": 0.0,
                    "trades": []
                }
            
            pairs_trading[pair]["open_positions"] += 1
            confidence = float(trade.get("confidence", 0))
            pairs_trading[pair]["total_confidence"] += confidence
            pairs_trading[pair]["trades"].append({
                "id": trade.get("id"),
                "side": trade.get("side"),
                "entry_price": float(trade.get("entry_price", 0)),
                "confidence": confidence,
                "opened_at": trade.get("opened_at")
            })
        
        # Calculate averages
        for pair_info in pairs_trading.values():
            if pair_info["open_positions"] > 0:
                pair_info["avg_confidence"] = round(
                    pair_info["total_confidence"] / pair_info["open_positions"], 1
                )
        
        return jsonify({
            "mode": mode,
            "active_pairs": list(pairs_trading.values()),
            "total_active_pairs": len(pairs_trading),
            "total_open_positions": len(all_trades),
            "timestamp": datetime.now(IST).isoformat()
        })
    except Exception as e:
        app.logger.error(f"Error fetching active pairs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/trades/by-pair")
def trades_by_pair():
    """Get all trades grouped by pair with confidence scores."""
    try:
        limit = int(request.args.get("limit", 100))
        mode = db.get_trading_mode()
        
        if mode == "PAPER":
            all_trades = db.get_all_paper_trades(limit)
        else:
            all_trades = db.get_all_trades(limit)
        
        # Group by pair
        pairs_stats = {}
        for trade in all_trades:
            pair = trade.get("pair")
            if pair not in pairs_stats:
                pairs_stats[pair] = {
                    "pair": pair,
                    "total_trades": 0,
                    "open_trades": 0,
                    "closed_trades": 0,
                    "total_confidence": 0.0,
                    "avg_confidence": 0.0,
                    "total_pnl": 0.0,
                    "win_rate": 0.0,
                    "recent_trades": []
                }
            
            status = trade.get("status", "")
            confidence = float(trade.get("confidence", 0))
            pnl = float(trade.get("pnl") or 0) if status == "closed" else None
            
            pairs_stats[pair]["total_trades"] += 1
            pairs_stats[pair]["total_confidence"] += confidence
            
            if status == "open":
                pairs_stats[pair]["open_trades"] += 1
            else:
                pairs_stats[pair]["closed_trades"] += 1
                if pnl is not None:
                    pairs_stats[pair]["total_pnl"] += pnl
            
            pairs_stats[pair]["recent_trades"].append({
                "id": trade.get("id"),
                "side": trade.get("side"),
                "status": status,
                "entry_price": float(trade.get("entry_price", 0)),
                "exit_price": float(trade.get("exit_price") or 0) if status == "closed" else None,
                "confidence": confidence,
                "pnl": pnl,
                "opened_at": trade.get("opened_at"),
                "closed_at": trade.get("closed_at")
            })
        
        # Calculate averages
        for pair_info in pairs_stats.values():
            if pair_info["total_trades"] > 0:
                pair_info["avg_confidence"] = round(
                    pair_info["total_confidence"] / pair_info["total_trades"], 1
                )
            if pair_info["closed_trades"] > 0:
                wins = sum(1 for t in pair_info["recent_trades"] 
                          if t["pnl"] is not None and t["pnl"] > 0)
                pair_info["win_rate"] = round(wins / pair_info["closed_trades"] * 100, 1)
        
        return jsonify({
            "mode": mode,
            "pairs_stats": list(pairs_stats.values()),
            "trading_pairs": len(pairs_stats),
            "timestamp": datetime.now(IST).isoformat()
        })
    except Exception as e:
        app.logger.error(f"Error fetching trades by pair: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pair_mode", methods=["GET", "POST"])
def pair_mode():
    """Pair mode is MULTI only: one process per enabled pair, max 3 open trades total."""
    if request.method == "GET":
        return jsonify({"pair_mode": "MULTI", "selected_pair": None})
    
    # POST - Accept for compatibility; always store MULTI
    try:
        data = request.get_json() or {}
        mode = str(data.get("pair_mode", "MULTI")).upper()
        if mode == "SINGLE":
            mode = "MULTI"
        db.set_pair_mode(mode, None)
        return jsonify({"success": True, "pair_mode": "MULTI", "selected_pair": None})
    except Exception as e:
        app.logger.error(f"Error setting pair mode: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pair_signals")
def pair_signals():
    """Get signal strength for enabled pairs only (up to 10 max)."""
    try:
        # Get ONLY enabled pair configs (user's favorites)
        enabled_pairs = db.get_enabled_pairs()
        
        if not enabled_pairs:
            app.logger.info("No enabled pairs found. Pairs are auto-enabled when confidence > 75%.")
            return jsonify({
                "pairs": [],
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            })
        
        client = CoinDCXREST("", "")
        results = []
        pairs_to_process = enabled_pairs[:10]
        app.logger.info(f"Processing {len(pairs_to_process)} enabled pairs (confidence from enabling strategy)")

        for idx, pair_config in enumerate(pairs_to_process, 1):
            pair = pair_config.get("pair")
            if not pair:
                continue
            enabled_by_strategy = pair_config.get("enabled_by_strategy")
            # Use the strategy that enabled this pair for confidence; fallback to active strategy for interval
            strat_instance = _get_strategy_instance(enabled_by_strategy) if enabled_by_strategy else None
            if not strat_instance and STRATEGY_MANAGER_LOADED:
                strat_instance = strategy_manager.strategy_manager.get_active_strategy()
            interval = "5m"
            if strat_instance:
                interval = strat_instance.get_config().get("interval", "5m")

            try:
                app.logger.debug(f"[{idx}/{len(pairs_to_process)}] Fetching candles for {pair}")
                candles = client.get_candles(pair, interval, limit=200)
                if not candles or len(candles) < 50:
                    out = {
                        "pair": pair,
                        "signal_strength": float(pair_config.get("enabled_at_confidence") or 0),
                        "enabled": pair_config.get("enabled", 0),
                        "leverage": pair_config.get("leverage", 5),
                        "quantity": pair_config.get("quantity", 0.001),
                        "inr_amount": pair_config.get("inr_amount", 300.0),
                        "enabled_by_strategy": enabled_by_strategy,
                        "enabled_at_confidence": pair_config.get("enabled_at_confidence"),
                    }
                    try:
                        exec_status = db.get_pair_execution_status_all().get(pair, {})
                        out["last_closed_at"] = exec_status.get("last_closed_at")
                        out["last_error"] = exec_status.get("last_error")
                    except Exception:
                        pass
                    results.append(out)
                    continue

                candles_norm = [{"open": c.get("open"), "high": c.get("high"), "low": c.get("low"), "close": c.get("close"), "volume": c.get("volume", 0), "time": c.get("time")} for c in candles]
                if strat_instance:
                    ev = strat_instance.evaluate(candles_norm, return_confidence=True)
                    confidence = float(ev.get("confidence", 0)) if isinstance(ev, dict) else 0.0
                else:
                    confidence = float(pair_config.get("enabled_at_confidence") or 0)

                out = {
                    "pair": pair,
                    "signal_strength": round(confidence, 1),
                    "enabled": pair_config.get("enabled", 0),
                    "leverage": pair_config.get("leverage", 5),
                    "quantity": pair_config.get("quantity", 0.001),
                    "inr_amount": pair_config.get("inr_amount", 300.0),
                    "enabled_by_strategy": enabled_by_strategy,
                    "enabled_at_confidence": pair_config.get("enabled_at_confidence"),
                    "last_price": candles[-1].get("close") if candles else None
                }
                try:
                    exec_status = db.get_pair_execution_status_all().get(pair, {})
                    out["last_closed_at"] = exec_status.get("last_closed_at")
                    out["last_error"] = exec_status.get("last_error")
                    out["last_signal"] = exec_status.get("last_signal")
                except Exception:
                    pass
                results.append(out)
                app.logger.debug(f"[{idx}/{len(pairs_to_process)}] {pair}: confidence={confidence:.1f}% ({enabled_by_strategy or 'active'})")
            except Exception as e:
                app.logger.warning(f"Confidence calculation failed for {pair}: {e}")
                out = {
                    "pair": pair,
                    "signal_strength": float(pair_config.get("enabled_at_confidence") or 0),
                    "enabled": pair_config.get("enabled", 0),
                    "leverage": pair_config.get("leverage", 5),
                    "quantity": pair_config.get("quantity", 0.001),
                    "inr_amount": pair_config.get("inr_amount", 300.0),
                    "enabled_by_strategy": enabled_by_strategy,
                    "enabled_at_confidence": pair_config.get("enabled_at_confidence"),
                }
                try:
                    exec_status = db.get_pair_execution_status_all().get(pair, {})
                    out["last_closed_at"] = exec_status.get("last_closed_at")
                    out["last_error"] = exec_status.get("last_error")
                except Exception:
                    pass
                results.append(out)

        # Sort by current confidence (signal_strength) highest first
        results.sort(key=lambda x: x["signal_strength"], reverse=True)
        
        app.logger.info(f"Pair signals ready: {len(results)} pairs, top signal: {results[0]['signal_strength']:.1f}% ({results[0]['pair']})" if results else "No pairs processed")
        
        return jsonify({
            "pairs": results,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        })
    except Exception as e:
        app.logger.error(f"Error fetching pair signals: {e}")
        return jsonify({"error": str(e)}), 500


# Allowed path for bot log (no user-controlled paths)
BOT_LOG_PATH = "/home/ubuntu/trading-bot/data/bot.log"

# Match Python logging asctime: "2026-02-24 16:55:32,123" or "2026-02-24 16:55:32"
_BOT_LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:[,.](\d+))?")


def _parse_log_timestamp(line):
    """Return (timestamp, line). Log asctime is local time; we use naive datetime so 2-day filter matches."""
    m = _BOT_LOG_TS_RE.match(line)
    if not m:
        return (float("inf"), line)
    date_part, ms = m.group(1), m.group(2)
    try:
        ts_str = date_part.replace(" ", "T") + (f".{ms.ljust(3, '0')[:3]}" if ms else ".000")
        dt = datetime.fromisoformat(ts_str)
        return (dt.timestamp(), line)
    except Exception:
        return (float("inf"), line)


def _log_line_to_ist(line: str) -> str:
    """Replace leading log timestamp with IST (UTC+5:30). Log timestamp is in server local time."""
    m = _BOT_LOG_TS_RE.match(line)
    if not m:
        return line
    date_part, ms = m.group(1), m.group(2)
    try:
        ts_str = date_part.replace(" ", "T") + (f".{ms.ljust(3, '0')[:3]}" if ms else ".000")
        dt_naive = datetime.fromisoformat(ts_str)
        # Python logging asctime uses server local time; convert to IST for display
        local_tz = datetime.now().astimezone().tzinfo
        dt_local = dt_naive.replace(tzinfo=local_tz) if local_tz else dt_naive.replace(tzinfo=timezone.utc)
        dt_ist = dt_local.astimezone(IST)
        ms_part = f",{ms.ljust(3, '0')[:3]}" if ms else ",000"
        ist_prefix = dt_ist.strftime("%Y-%m-%d %H:%M:%S") + ms_part
        return ist_prefix + line[m.end():]
    except Exception:
        return line


# Keep only logs from the last 2 days (trade histories are in DB and kept separately)
BOT_LOG_RETENTION_DAYS = 2


@app.route("/api/bot_logs")
def bot_logs():
    """Return last N lines of bot.log, newest first (desc), only lines from the last 2 days."""
    try:
        n = request.args.get("n", 200, type=int)
        n = min(max(1, n), 1000)
        filter_exec = request.args.get("filter") == "execution"
        if not os.path.isfile(BOT_LOG_PATH):
            return jsonify({"lines": [], "path": BOT_LOG_PATH, "error": "Log file not found"})
        with open(BOT_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        lines = [line.rstrip("\n") for line in all_lines]
        if filter_exec:
            keywords = (
                "Closed candle", "Signal:", "PAPER entry", "Signal rejected", "Execution allowed",
                "wallet not initialized", "Skip execution", "Max open trades", "Per-pair limit",
                "No signal from strategy", "Paper trade failed", "PAPER entry skipped", "insufficient for fee",
                "Re-entry cooldown", "No strategy"
            )
            lines = [ln for ln in lines if any(kw in ln for kw in keywords)]
        # Parse timestamps and keep only last 2 days (use local time to match log asctime)
        cutoff = (datetime.now() - timedelta(days=BOT_LOG_RETENTION_DAYS)).timestamp()
        parsed = [_parse_log_timestamp(ln) for ln in lines]
        parsed = [(ts, ln) for ts, ln in parsed if ts != float("inf") and ts >= cutoff]
        # Sort descending (newest first)
        parsed.sort(key=lambda x: x[0], reverse=True)
        sorted_lines = [ln for _, ln in parsed[:n]]
        # Convert timestamps to IST for display
        sorted_lines = [_log_line_to_ist(ln) for ln in sorted_lines]
        return jsonify({"lines": sorted_lines, "path": BOT_LOG_PATH})
    except Exception as e:
        app.logger.error(f"Error reading bot logs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/live/positions")
def live_positions():
    """Get actual open positions from CoinDCX using List Positions endpoint."""
    try:
        import hmac
        import hashlib
        import time
        import json
        import requests
        from dotenv import load_dotenv
        
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key = os.getenv("COINDCX_API_KEY")
        secret = os.getenv("COINDCX_API_SECRET")

        if not key or not secret:
            return jsonify({"error": "API credentials not configured"}), 500

        # Use List Positions endpoint and request INR-margined futures
        timeStamp = int(round(time.time() * 1000))
        body = {
            "timestamp": timeStamp,
            "page": "1",
            "size": "100",
            # IMPORTANT: Platform shows positions under INR margin wallet,
            # so we must request INR-margined positions here.
            "margin_currency_short_name": ["INR"]
        }
        
        json_body = json.dumps(body, separators=(',', ':'))
        secret_bytes = bytes(secret, encoding='utf-8')
        signature = hmac.new(secret_bytes, json_body.encode(), hashlib.sha256).hexdigest()
        
        headers = {
            'Content-Type': 'application/json',
            'X-AUTH-APIKEY': key,
            'X-AUTH-SIGNATURE': signature
        }
        
        resp = requests.post(
            "https://api.coindcx.com/exchange/v1/derivatives/futures/positions",
            data=json_body,
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        positions = resp.json()
        
        if not isinstance(positions, list):
            return jsonify([])

        # Filter for actual open positions (active_pos != 0)
        result = []
        for pos in positions:
            try:
                active_pos = pos.get("active_pos", 0)
                if not active_pos:
                    # Skip configs / inactive rows
                    continue

                # Determine side from active_pos sign
                qty = float(active_pos)
                quantity = abs(qty)
                side = "buy" if qty > 0 else "sell"
                
                pair = pos.get("pair", "")
                position_id = pos.get("id", "")
                entry_price = float(pos.get("avg_price", 0) or 0)
                leverage = int(pos.get("leverage", 1) or 1)
                locked_margin = float(pos.get("locked_margin", 0) or 0)

                # Mark / index price for live P&L (fallback to any reasonable field)
                mark_price = None
                for key_name in ("mark_price", "index_price", "last_price", "current_price", "price"):
                    raw = pos.get(key_name)
                    if raw is not None:
                        try:
                            mark_price = float(raw)
                            break
                        except (TypeError, ValueError):
                            continue

                # Compute unrealized P&L in INR if possible
                unrealized_pnl = None
                if mark_price is not None and entry_price and quantity:
                    # If settlement_currency_avg_price is provided (e.g. INR/USDT),
                    # use it to convert P&L into INR to match platform display.
                    settlement_rate_raw = pos.get("settlement_currency_avg_price")
                    try:
                        settlement_rate = float(settlement_rate_raw) if settlement_rate_raw not in (None, 0, "") else None
                    except (TypeError, ValueError):
                        settlement_rate = None

                    price_diff = (mark_price - entry_price) if side == "buy" else (entry_price - mark_price)
                    if settlement_rate and settlement_rate > 0:
                        unrealized_pnl = price_diff * quantity * leverage * settlement_rate
                    else:
                        # Fallback: units will be in quote currency (e.g. USDT)
                        unrealized_pnl = price_diff * quantity * leverage
                else:
                    # Fallback: try API-provided unrealized fields if any
                    for key_name in ("unrealized_pnl", "mtm_pnl", "pnl"):
                        raw = pos.get(key_name)
                        if raw is not None:
                            try:
                                unrealized_pnl = float(raw)
                                break
                            except (TypeError, ValueError):
                                continue

                # Get TP/SL from triggers (may be null for manual positions)
                tp_price = pos.get("take_profit_trigger")
                sl_price = pos.get("stop_loss_trigger")

                # Convert timestamp (ms since epoch) to IST ISO string for dashboard
                opened_raw = pos.get("activation_time") or pos.get("updated_at") or pos.get("created_at")
                opened_at = None
                from datetime import datetime, timezone
                try:
                    if isinstance(opened_raw, (int, float)):
                        dt = datetime.fromtimestamp(opened_raw / 1000.0, tz=timezone.utc)
                        opened_at = dt.astimezone(IST).isoformat()
                    elif isinstance(opened_raw, str) and opened_raw:
                        opened_at = opened_raw
                except Exception:
                    opened_at = None
                
                result.append({
                    "position_id": position_id,
                    "pair": pair,
                    "side": side,
                    "entry_price": entry_price,
                    "quantity": quantity,
                    "leverage": leverage,
                    "tp_price": float(tp_price) if tp_price else None,
                    "sl_price": float(sl_price) if sl_price else None,
                    "unrealized_pnl": unrealized_pnl if unrealized_pnl is not None else 0.0,
                    "margin": locked_margin,
                    "mark_price": mark_price,
                    "opened_at": opened_at,
                    "status": "open",
                    "source": "live"
                })
            except Exception as inner_e:
                app.logger.warning(f"Failed to parse live position row: {inner_e} | raw={pos}")

        return jsonify(result)

    except Exception as e:
        app.logger.error(f"Error fetching live positions: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug/positions")
def debug_positions():
    """Debug endpoint - returns raw CoinDCX positions response to identify field names."""
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key = os.getenv("COINDCX_API_KEY")
        secret = os.getenv("COINDCX_API_SECRET")
        if not key or not secret:
            return jsonify({"error": "No credentials"}), 500
        client = CoinDCXREST(key, secret)
        positions = client.get_positions()
        return jsonify({"count": len(positions), "raw": positions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500




# Start batch checker on module load (works with both app.run and gunicorn)
_start_batch_checker()

if __name__ == "__main__":
    # When run as "python app.py": enable SocketIO + live chart relay. When run under gunicorn, app stays plain Flask (no 502).
    try:
        from flask_socketio import SocketIO, join_room
        _sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
        _relay_state = {
            "lock": threading.Lock(),
            "requested_pair": None,
            "requested_interval": "5m",
            "socket": None,
            "thread": None,
            "running": True,
        }

        def _relay_thread():
            import os
            from dotenv import load_dotenv
            load_dotenv("/home/ubuntu/trading-bot/.env")
            key = os.getenv("COINDCX_API_KEY") or os.getenv("API_KEY")
            secret = os.getenv("COINDCX_API_SECRET") or os.getenv("API_SECRET")
            if not key or not secret:
                app.logger.warning("Chart relay: no API credentials, live chart disabled")
                return
            while _relay_state["running"]:
                with _relay_state["lock"]:
                    pair = _relay_state["requested_pair"]
                    interval = _relay_state["requested_interval"]
                if not pair:
                    time.sleep(1)
                    continue
                try:
                    dcx = CoinDCXSocket(key, secret)
                    with _relay_state["lock"]:
                        _relay_state["socket"] = dcx
                    def _on_candle(data):
                        try:
                            t_raw = data.get("t") or data.get("timestamp")
                            ts_sec = int(t_raw) if t_raw is not None else None
                            if ts_sec is not None and ts_sec > 1e10:
                                ts_sec = ts_sec // 1000
                            if ts_sec is None:
                                ts_sec = int(time.time())
                            _sio.emit("candlestick", {
                                "pair": pair, "interval": interval, "time": ts_sec,
                                "open": float(data.get("o", 0)), "high": float(data.get("h", 0)),
                                "low": float(data.get("l", 0)), "close": float(data.get("c", 0)),
                                "isClosed": bool(data.get("x", False)),
                            }, room="chart")
                        except Exception as e:
                            app.logger.debug(f"Chart relay emit: {e}")
                    dcx.on("candlestick", _on_candle)
                    dcx.connect(pair, interval)
                    dcx.wait()
                except Exception as e:
                    app.logger.debug(f"Chart relay: {e}")
                finally:
                    with _relay_state["lock"]:
                        _relay_state["socket"] = None
                time.sleep(0.5)

        @_sio.on("connect")
        def _chart_connect():
            pass

        @_sio.on("subscribe_candles")
        def _chart_subscribe(data):
            try:
                pair = (data or {}).get("pair") or (data or {}).get("pair_id")
                interval = (data or {}).get("interval", "5m")
                if not pair:
                    return
                with _relay_state["lock"]:
                    _relay_state["requested_pair"] = pair
                    _relay_state["requested_interval"] = interval
                    if _relay_state["thread"] is None or not _relay_state["thread"].is_alive():
                        _relay_state["thread"] = threading.Thread(target=_relay_thread, daemon=True)
                        _relay_state["thread"].start()
                    sock = _relay_state.get("socket")
                    if sock is not None:
                        try:
                            sock.disconnect()
                        except Exception:
                            pass
                join_room("chart")
            except Exception as e:
                app.logger.debug(f"subscribe_candles: {e}")

        _sio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
    except ImportError:
        app.run(host="0.0.0.0", port=5000, debug=False)
