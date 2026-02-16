#!/usr/bin/env python3
"""
Test the official CoinDCX Futures Wallet API endpoint
Based on: https://docs.coindcx.com/#wallet-details
"""

import os
import sys
import json
import hmac
import hashlib
import time
import requests

# Load .env manually
def load_env_file(filepath=".env"):
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

env_vars = load_env_file(".env") or load_env_file("/home/ubuntu/trading-bot/.env")
API_KEY = env_vars.get("COINDCX_API_KEY") or os.getenv("COINDCX_API_KEY")
API_SECRET = env_vars.get("COINDCX_API_SECRET") or os.getenv("COINDCX_API_SECRET")

if not API_KEY or not API_SECRET:
    print("❌ Error: API credentials not found")
    sys.exit(1)

print("="*70)
print("Testing CoinDCX Futures Wallet API (Official Endpoint)")
print("="*70)
print(f"API Key: {API_KEY[:10]}...{API_KEY[-4:]}")
print(f"API Secret: ***{API_SECRET[-4:]}")
print()

# Create signature
body = {"timestamp": int(time.time() * 1000)}
secret_bytes = bytes(API_SECRET, encoding='utf-8')
json_body = json.dumps(body, separators=(',', ':'))
message = bytes(json_body, encoding='utf-8')
signature = hmac.new(secret_bytes, message, hashlib.sha256).hexdigest()

# Headers
headers = {
    'Content-Type': 'application/json',
    'X-AUTH-APIKEY': API_KEY,
    'X-AUTH-SIGNATURE': signature
}

# Official endpoint from docs
url = "https://api.coindcx.com/exchange/v1/derivatives/futures/wallets"

print(f"Endpoint: GET {url}")
print(f"Request body: {json_body}")
print(f"Signature: {signature[:20]}...")
print()

try:
    # GET request with the EXACT JSON string that was signed
    # CRITICAL: Use data=json_body not json=body to match signature
    response = requests.get(url, data=json_body, headers=headers, timeout=10)
    
    print(f"Status Code: {response.status_code}")
    print()
    
    if response.status_code == 200:
        data = response.json()
        print("✅ SUCCESS! Wallet data received:")
        print(json.dumps(data, indent=2))
        print()
        
        # Parse wallet balances
        if isinstance(data, list):
            print("=" * 70)
            print("Wallet Balances:")
            print("=" * 70)
            for wallet in data:
                currency = wallet.get('currency_short_name', 'UNKNOWN')
                balance = wallet.get('balance', '0')
                locked = wallet.get('locked_balance', '0')
                print(f"  {currency:6} | Balance: {balance:>15} | Locked: {locked:>15}")
            print("=" * 70)
        else:
            print("⚠️  Unexpected response format (not an array)")
            
    else:
        error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
        print(f"❌ ERROR: HTTP {response.status_code}")
        print(json.dumps(error_data, indent=2) if isinstance(error_data, dict) else error_data)
        
except Exception as e:
    print(f"❌ Exception: {e}")
    import traceback
    traceback.print_exc()
