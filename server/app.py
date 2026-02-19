import sys
import os
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

from coindcx import CoinDCXREST

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

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
            if not STRATEGY_MANAGER_LOADED:
                return jsonify({
                    "strategies": [],
                    "active": None,
                    "error": "Strategy manager not loaded"
                }), 500
            
            available_strategies = strategy_manager.strategy_manager.get_available_strategies()
            active_strategy = strategy_manager.strategy_manager.get_active_strategy_name()
            
            result = {
                "strategies": [{"name": s["name"], "displayName": s.get("display_name", s["name"]), "description": s["description"]} for s in available_strategies],
                "active": active_strategy
            }
            return jsonify(result)
        except Exception as e:
            return jsonify({
                "strategies": [],
                "active": None,
                "error": str(e)
            }), 500

    if not STRATEGY_MANAGER_LOADED:
        return jsonify({"error": "Strategy manager not loaded"}), 500

    data = request.get_json() or {}
    strategy_name = str(data.get("strategy", "")).strip()
    
    if not strategy_name:
        return jsonify({"error": "strategy name is required"}), 400

    try:
        strategy_manager.strategy_manager.set_active_strategy(strategy_name)
        db.log_event("INFO", f"Active strategy changed to {strategy_name}")
        return jsonify({"success": True, "strategy": strategy_name})
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
        
        for pair in pairs[:20]:
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
        limit = int(request.args.get("limit", 100))
        
        if limit > 500:
            limit = 500
        
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
            return jsonify({"success": True, "message": "Bot started"})
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
            db.log_event("WARNING", "Bot stopped manually from dashboard")
            return jsonify({"success": True, "message": "Bot stopped"})
        return jsonify({"success": False, "message": result.stderr or "Failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/bot/status")
def bot_status():
    import subprocess
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "is-active", "bot"],
            capture_output=True, text=True, timeout=5
        )
        is_running = result.stdout.strip() == "active"
        return jsonify({"running": is_running})
    except Exception:
        return jsonify({"running": False})


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
    """Get or set pair trading mode (SINGLE/MULTI) and selected pair."""
    if request.method == "GET":
        try:
            mode_data = db.get_pair_mode()
            return jsonify(mode_data)
        except Exception as e:
            app.logger.error(f"Error getting pair mode: {e}")
            return jsonify({"pair_mode": "MULTI", "selected_pair": None})
    
    # POST - Set pair mode
    try:
        data = request.get_json() or {}
        mode = str(data.get("pair_mode", "MULTI")).upper()
        selected_pair = data.get("selected_pair")
        
        if mode not in ("SINGLE", "MULTI"):
            return jsonify({"error": "pair_mode must be SINGLE or MULTI"}), 400
        
        if mode == "SINGLE" and not selected_pair:
            return jsonify({"error": "selected_pair is required for SINGLE mode"}), 400
        
        db.set_pair_mode(mode, selected_pair)
        db.log_event("INFO", f"Pair mode set to {mode}" + (f" with pair {selected_pair}" if selected_pair else ""))
        
        return jsonify({
            "success": True,
            "pair_mode": mode,
            "selected_pair": selected_pair
        })
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
            app.logger.info("No enabled pairs found. Enable pairs in Pair Manager.")
            return jsonify([])
        
        # Import strategy to calculate signal strength
        try:
            import strategy
        except Exception as e:
            app.logger.error(f"Failed to import strategy: {e}")
            return jsonify({"error": "Strategy module not available"}), 500
        
        client = CoinDCXREST("", "")
        results = []
        
        # Get active strategy config for interval
        active_strategy = None
        interval = "5m"  # default
        try:
            if STRATEGY_MANAGER_LOADED:
                active_strategy = strategy_manager.strategy_manager.get_active_strategy()
                if active_strategy:
                    interval = active_strategy.get_config().get("interval", "5m")
        except Exception:
            pass
        
        # Process only enabled pairs (limit to 10 max for performance)
        # This keeps response time under 20 seconds
        pairs_to_process = enabled_pairs[:10]
        app.logger.info(f"Processing {len(pairs_to_process)} enabled pairs for signal strength")
        
        for idx, pair_config in enumerate(pairs_to_process, 1):
            pair = pair_config.get("pair")
            if not pair:
                continue
            
            try:
                # Fetch candles for this pair
                app.logger.debug(f"[{idx}/{len(pairs_to_process)}] Fetching candles for {pair}")
                candles = client.get_candles(pair, interval, limit=150)
                
                if not candles or len(candles) < 50:
                    results.append({
                        "pair": pair,
                        "signal_strength": 0.0,
                        "enabled": pair_config.get("enabled", 0),
                        "leverage": pair_config.get("leverage", 5),
                        "quantity": pair_config.get("quantity", 0.001),
                        "inr_amount": pair_config.get("inr_amount", 300.0)
                    })
                    continue
                
                # Calculate signal strength
                signal_strength = strategy.calculate_signal_strength(candles)
                
                results.append({
                    "pair": pair,
                    "signal_strength": signal_strength,
                    "enabled": pair_config.get("enabled", 0),
                    "leverage": pair_config.get("leverage", 5),
                    "quantity": pair_config.get("quantity", 0.001),
                    "inr_amount": pair_config.get("inr_amount", 300.0),
                    "last_price": candles[-1].get("close") if candles else None
                })
                app.logger.debug(f"[{idx}/{len(pairs_to_process)}] {pair}: signal={signal_strength:.1f}%")
            except Exception as e:
                app.logger.warning(f"Signal strength calculation failed for {pair}: {e}")
                results.append({
                    "pair": pair,
                    "signal_strength": 0.0,
                    "enabled": pair_config.get("enabled", 0),
                    "leverage": pair_config.get("leverage", 5),
                    "quantity": pair_config.get("quantity", 0.001),
                    "inr_amount": pair_config.get("inr_amount", 300.0)
                })
        
        # Sort by signal strength (highest first)
        results.sort(key=lambda x: x["signal_strength"], reverse=True)
        
        app.logger.info(f"Pair signals ready: {len(results)} pairs, top signal: {results[0]['signal_strength']:.1f}% ({results[0]['pair']})" if results else "No pairs processed")
        
        return jsonify(results)
    except Exception as e:
        app.logger.error(f"Error fetching pair signals: {e}")
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




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
