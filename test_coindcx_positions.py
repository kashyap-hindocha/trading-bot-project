#!/usr/bin/env python3
"""Test script to check CoinDCX positions API directly"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bot.coindcx import CoinDCXREST
from dotenv import load_dotenv
import json
import hmac
import hashlib
import time
import requests

# Load credentials from server
load_dotenv("/home/ubuntu/trading-bot/.env")
key = os.getenv("COINDCX_API_KEY")
secret = os.getenv("COINDCX_API_SECRET")

if not key or not secret:
    print("ERROR: No API credentials found")
    sys.exit(1)

print("Connecting to CoinDCX...")

print("\n" + "="*60)
print("Testing LIST POSITIONS endpoint (per documentation)")
print("="*60)

# Use the documented endpoint for listing positions
timeStamp = int(round(time.time() * 1000))
body = {
    "timestamp": timeStamp,
    "page": "1",
    "size": "100",
    "margin_currency_short_name": ["INR"]
}
json_body = json.dumps(body, separators=(',', ':'))
signature = hmac.new(bytes(secret, encoding='utf-8'), json_body.encode(), hashlib.sha256).hexdigest()

url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions"
headers = {
    'Content-Type': 'application/json',
    'X-AUTH-APIKEY': key,
    'X-AUTH-SIGNATURE': signature
}

response = requests.post(url, data=json_body, headers=headers)
positions = response.json()

print(f"Response type: {type(positions)}")
print(f"Total positions returned: {len(positions) if isinstance(positions, list) else 'N/A'}")

if isinstance(positions, list):
    # Filter for positions with active_pos != 0 (actual open positions)
    active = [p for p in positions if p.get('active_pos', 0) != 0]
    print(f"\nPositions with active_pos != 0: {len(active)}")
    
    if active:
        print("\n✅ ACTIVE POSITIONS FOUND:")
        for p in active:
            print(f"\nPair: {p.get('pair')}")
            print(f"  active_pos: {p.get('active_pos')}")
            print(f"  avg_price: {p.get('avg_price')}")
            print(f"  locked_margin: {p.get('locked_margin')}")
            print(f"  leverage: {p.get('leverage')}")
            print(json.dumps(p, indent=2))
    else:
        print("\n❌ NO ACTIVE POSITIONS (all active_pos = 0)")
        print("\nChecking for PIPPIN/1000PEPE specifically:")
        pippin = [p for p in positions if 'PIP' in p.get('pair', '').upper() or 'PEPE' in p.get('pair', '').upper()]
        if pippin:
            print("Found PIPPIN/PEPE position config:")
            print(json.dumps(pippin[0], indent=2))
        else:
            print("No PIPPIN/PEPE found. Checking first 3 positions:")
            for p in positions[:3]:
                print(f"{p.get('pair')}: active_pos={p.get('active_pos')}")

