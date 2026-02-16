import sys
import os
sys.path.insert(0, '/home/ubuntu/trading-bot/bot')

from flask import Flask, jsonify
from flask_cors import CORS
import db
from coindcx import CoinDCXREST

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
                node.get("currency")
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

    wallet_paths = (
        "/exchange/v1/derivatives/futures/wallets",
        "/exchange/v1/derivatives/futures/wallet",
        "/exchange/v1/derivatives/futures/data/wallet",
        "/exchange/v1/derivatives/futures/account",
        "/exchange/v1/derivatives/futures/data/account",
        "/exchange/v1/derivatives/futures/balance",
    )

    last_error = None
    attempts = []

    for path in wallet_paths:
        for method_name in ["POST", "GET"]:
            try:
                # Create fresh timestamp for each request
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

                if method_name == "POST":
                    resp = requests.post(
                        f"https://api.coindcx.com{path}",
                        headers=headers,
                        json=body,
                        timeout=5,
                    )
                else:
                    # GET request - CoinDCX expects body as JSON even for GET
                    resp = requests.get(
                        f"https://api.coindcx.com{path}",
                        headers=headers,
                        json=body,
                        timeout=5,
                    )
                
                attempt_info = {
                    "path": path,
                    "method": method_name,
                    "status": resp.status_code
                }
                
                try:
                    payload = resp.json()
                    attempt_info["response"] = payload
                except:
                    attempt_info["response"] = resp.text[:200]
                
                attempts.append(attempt_info)
                
                # Skip 404 not found
                if _is_not_found_payload(payload if isinstance(payload, dict) else {}):
                    continue
                
                # Accept 2xx responses
                if 200 <= resp.status_code < 300:
                    if debug:
                        return {"payload": payload, "attempts": attempts}
                    return payload
                
                # Store last error for debugging
                if resp.status_code >= 400:
                    last_error = payload if isinstance(payload, dict) else {"error": resp.text[:200]}
                    
            except (requests.RequestException, ValueError) as e:
                attempts.append({
                    "path": path,
                    "method": method_name,
                    "error": str(e)
                })
                continue

    if debug:
        return {"error": "No valid endpoint found", "last_error": last_error, "attempts": attempts}
    
    return None


@app.route("/api/status")
def status():
    balance = 0.0
    balance_currency = "INR"
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/trading-bot/.env")
        key    = os.getenv("COINDCX_API_KEY")
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
    except Exception as exc:
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
    })


@app.route("/api/positions")
def positions():
    return jsonify(db.get_open_trades())


@app.route("/api/trades")
def trades():
    return jsonify(db.get_all_trades(limit=100))


@app.route("/api/stats")
def stats():
    return jsonify(db.get_trade_stats())


@app.route("/api/equity")
def equity():
    return jsonify(db.get_equity_history(limit=200))


@app.route("/api/logs")
def logs():
    return jsonify(db.get_recent_logs(limit=50))


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
