#!/usr/bin/env python3
"""
Test CoinDCX balance API using the EXACT format from official docs
Based on: https://docs.coindcx.com/
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

print(f"✓ API Key: {API_KEY[:10]}...{API_KEY[-4:]}")
print(f"✓ API Secret: ***{API_SECRET[-4:]}\n")

def make_request(endpoint, method="POST"):
    """Make authenticated request to CoinDCX API"""
    
    # Create request body with timestamp
    body = {
        "timestamp": int(time.time() * 1000)
    }
    
    # Create signature (EXACT format from CoinDCX docs)
    secret_bytes = bytes(API_SECRET, encoding='utf-8')
    json_body = json.dumps(body, separators=(',', ':'))
    message = bytes(json_body, encoding='utf-8')
    
    signature = hmac.new(secret_bytes, message, hashlib.sha256).hexdigest()
    
    # Headers (EXACT format from CoinDCX docs)
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': signature
    }
    
    url = f"https://api.coindcx.com{endpoint}"
    
    print(f"\n{'='*70}")
    print(f"Testing: {method} {endpoint}")
    print(f"{'='*70}")
    print(f"Request body: {json_body}")
    print(f"Signature: {signature[:20]}...")
    
    try:
        if method == "POST":
            response = requests.post(url, data=json_body, headers=headers, timeout=10)
        else:
            response = requests.get(url, data=json_body, headers=headers, timeout=10)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        # Try to parse JSON response
        try:
            data = response.json()
            print(f"\nResponse JSON:")
            print(json.dumps(data, indent=2))
            return data
        except:
            print(f"\nResponse Text:")
            print(response.text)
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

# Test these endpoints based on CoinDCX patterns
print("\n" + "="*70)
print("TESTING COINDCX BALANCE ENDPOINTS")
print("="*70)

endpoints_to_test = [
    # Based on the pattern from create order endpoint
    "/exchange/v1/users/balances",          # Spot wallets
    "/exchange/v1/users/info",              # User account info
    "/exchange/v1/account/balances",        # Account balances
    
    # Futures specific (matching the /orders/create pattern)
    "/exchange/v1/derivatives/futures/user",
    "/exchange/v1/derivatives/futures/account",
]

for endpoint in endpoints_to_test:
    result = make_request(endpoint, "POST")
    
    if result and isinstance(result, dict):
        # Look for balance fields
        if any(key in str(result).lower() for key in ['balance', 'wallet', 'usdt', 'inr']):
            print("\n💰 POTENTIAL BALANCE DATA FOUND!")
            
print("\n" + "="*70)
print("Testing complete!")
print("="*70)
