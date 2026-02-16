#!/usr/bin/env python3
"""
Test script to verify CoinDCX Futures balance API
Run this to debug which endpoint works for fetching your wallet balance.
"""

import os
import sys
import json
import hmac
import hashlib
import time
import requests

# Load environment variables manually (no dependencies needed)
def load_env_file(filepath=".env"):
    """Simple .env file parser without requiring python-dotenv"""
    env_vars = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return env_vars

# Try multiple .env locations
env_vars = load_env_file(".env") or load_env_file("/home/ubuntu/trading-bot/.env")

API_KEY = env_vars.get("COINDCX_API_KEY") or os.getenv("COINDCX_API_KEY")
API_SECRET = env_vars.get("COINDCX_API_SECRET") or os.getenv("COINDCX_API_SECRET")

if not API_KEY or not API_SECRET:
    print("❌ Error: COINDCX_API_KEY and COINDCX_API_SECRET not found in .env file")
    sys.exit(1)

print(f"✓ API Key: {API_KEY[:10]}...{API_KEY[-4:]}")
print(f"✓ API Secret: ***{API_SECRET[-4:]}")
print()

# Test endpoints for futures wallet balance
TEST_ENDPOINTS = [
    "/exchange/v1/derivatives/futures/data/wallet_balances",
    "/exchange/v1/derivatives/futures/user/wallet_balances",
    "/exchange/v1/derivatives/futures/user/balance",
    "/api/v1/derivatives/futures/data/wallet_balances",
    "/exchange/v1/derivatives/futures/wallet_balances",
    "/exchange/v1/derivatives/futures/balances",
    "/exchange/v1/derivatives/futures/user/wallet",
]

BASE_URL = "https://api.coindcx.com"


def test_endpoint(path, method="POST"):
    """Test a single endpoint with both POST and GET methods."""
    try:
        body = {"timestamp": int(time.time() * 1000)}
        
        # Create signature
        json_body = json.dumps(body, separators=(",", ":"))
        signature = hmac.new(
            API_SECRET.encode(),
            json_body.encode(),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": API_KEY,
            "X-AUTH-SIGNATURE": signature,
        }
        
        url = BASE_URL + path
        
        if method == "POST":
            response = requests.post(url, headers=headers, json=body, timeout=10)
        else:
            response = requests.get(url, headers=headers, json=body, timeout=10)
        
        return {
            "status_code": response.status_code,
            "success": 200 <= response.status_code < 300,
            "response": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text[:200],
        }
        
    except Exception as e:
        return {
            "status_code": 0,
            "success": False,
            "error": str(e),
        }


def extract_balance_from_response(response_data):
    """Try to extract USDT balance from various response formats."""
    if not isinstance(response_data, (dict, list)):
        return None
    
    # Common balance field names
    balance_keys = [
        "available_balance", "availableBalance",
        "wallet_balance", "walletBalance",
        "balance", "total_balance", "totalBalance",
        "usdt_balance", "usdtBalance",
    ]
    
    def search(data):
        if isinstance(data, dict):
            # Check if this is a USDT entry
            currency = data.get("currency") or data.get("asset") or data.get("symbol")
            if currency and "USDT" in str(currency).upper():
                for key in balance_keys:
                    if key in data:
                        try:
                            return float(data[key])
                        except (ValueError, TypeError):
                            pass
            
            # Recursively search
            for key in balance_keys:
                if key in data:
                    try:
                        return float(data[key])
                    except (ValueError, TypeError):
                        pass
            
            for value in data.values():
                result = search(value)
                if result is not None:
                    return result
                    
        elif isinstance(data, list):
            for item in data:
                result = search(item)
                if result is not None:
                    return result
        
        return None
    
    return search(response_data)


print("=" * 70)
print("Testing CoinDCX Futures Balance API Endpoints")
print("=" * 70)
print()

successful_endpoints = []

for endpoint in TEST_ENDPOINTS:
    print(f"Testing: {endpoint}")
    print("-" * 70)
    
    for method in ["POST", "GET"]:
        result = test_endpoint(endpoint, method)
        
        status_icon = "✅" if result["success"] else "❌"
        print(f"  {status_icon} {method:4} → Status: {result['status_code']}")
        
        if result["success"]:
            response_data = result.get("response", {})
            print(f"      Response: {json.dumps(response_data, indent=2)[:500]}...")
            
            # Try to extract balance
            balance = extract_balance_from_response(response_data)
            if balance is not None:
                print(f"      💰 BALANCE FOUND: {balance} USDT")
                successful_endpoints.append({
                    "endpoint": endpoint,
                    "method": method,
                    "balance": balance,
                    "response": response_data
                })
            else:
                print(f"      ⚠️  Response received but couldn't extract balance")
        elif "error" in result:
            print(f"      Error: {result['error']}")
        else:
            error_msg = result.get("response", {})
            if isinstance(error_msg, dict):
                print(f"      Error: {error_msg.get('message', error_msg)}")
    
    print()

print("=" * 70)
print("Summary")
print("=" * 70)

if successful_endpoints:
    print(f"\n✅ Found {len(successful_endpoints)} working endpoint(s):\n")
    for ep in successful_endpoints:
        print(f"   Endpoint: {ep['endpoint']}")
        print(f"   Method:   {ep['method']}")
        print(f"   Balance:  {ep['balance']} USDT")
        print(f"   Response: {json.dumps(ep['response'], indent=2)[:300]}...")
        print()
else:
    print("\n❌ No working endpoints found!")
    print("\nPossible issues:")
    print("  1. API credentials might be incorrect")
    print("  2. Futures trading might not be enabled on your account")
    print("  3. CoinDCX API might have changed their endpoints")
    print("  4. Your account might not have any USDT balance")
    print("\nNext steps:")
    print("  - Verify your API keys have futures trading permissions")
    print("  - Check CoinDCX API documentation for updated endpoints")
    print("  - Contact CoinDCX support for correct futures API endpoints")
