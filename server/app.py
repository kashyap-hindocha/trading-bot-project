import sys
import os
sys.path.insert(0, '/home/ubuntu/trading-bot/bot')

from flask import Flask, jsonify, request
from flask_cors import CORS
import db
from coindcx import CoinDCXREST
import strategy

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
        return jsonify(db.get_recent_logs(limit=50))
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


@app.route("/api/paper/balance")
def paper_balance():
    return jsonify({"balance": db.get_paper_wallet_balance()})


@app.route("/api/paper/reset", methods=["POST"])
def paper_reset():
    real_balance, _ = _get_real_balance()
    db.set_paper_wallet_balance(real_balance)
    db.log_event("INFO", f"Paper balance reset to {real_balance}")
    return jsonify({"success": True, "balance": real_balance})


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
    ema_fast_series = _ema(closes, strategy.CONFIG["ema_fast"])
    ema_slow_series = _ema(closes, strategy.CONFIG["ema_slow"])
    if not ema_fast_series or not ema_slow_series:
        return None

    ema_fast = ema_fast_series[-1]
    ema_slow = ema_slow_series[-1]
    rsi = _rsi(closes, strategy.CONFIG["rsi_period"])
    overbought = strategy.CONFIG["rsi_overbought"]
    oversold = strategy.CONFIG["rsi_oversold"]

    price = closes[-1] if closes else 0
    gap = abs(ema_fast - ema_slow)
    gap_pct = (gap / price) if price else 0
    gap_max = 0.003

    def score_gap(local_gap):
        if local_gap >= gap_max:
            return 0.0
        return max(0.0, 1 - (local_gap / gap_max))

    ema_buy_score = score_gap(gap) if ema_fast <= ema_slow else 0.0
    ema_sell_score = score_gap(gap) if ema_fast >= ema_slow else 0.0

    rsi_band = 20.0
    rsi_buy_score = 1.0 if rsi <= oversold else max(0.0, 1 - ((rsi - oversold) / rsi_band))
    rsi_sell_score = 1.0 if rsi >= overbought else max(0.0, 1 - ((overbought - rsi) / rsi_band))

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
    pairs_raw = request.args.get("pairs", "")
    pairs = [p.strip() for p in pairs_raw.split(",") if p.strip()]
    if not pairs:
        return jsonify([])

    client = CoinDCXREST("", "")
    results = []
    for pair in pairs[:20]:
        try:
            candles = client.get_candles(pair, strategy.CONFIG["interval"], limit=150)
            closes = [c.get("close") for c in candles if c.get("close") is not None]
            readiness = _compute_readiness(closes)
            if readiness:
                results.append({"pair": pair, **readiness})
        except Exception as e:
            app.logger.warning(f"Readiness failed for {pair}: {e}")
    return jsonify(results)


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
        leverage = int(data.get("leverage", 5))
        quantity = float(data.get("quantity", 0.001))
        
        if not pair:
            return jsonify({"error": "Pair is required"}), 400
        
        db.upsert_pair_config(pair, enabled, leverage, quantity)
        db.log_event("INFO", f"Updated config for {pair}: enabled={enabled}, leverage={leverage}, qty={quantity}")
        
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
            
            if pair:
                db.upsert_pair_config(pair, enabled, leverage, quantity)
        
        db.log_event("INFO", f"Bulk updated {len(pairs)} pair configurations")
        return jsonify({"success": True, "message": f"Updated {len(pairs)} pairs"})
    except Exception as e:
        app.logger.error(f"Error bulk updating pairs: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
