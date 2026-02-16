"""
CoinDCX Futures API Wrapper
Handles: Authentication, REST calls, WebSocket (socketio v2)
"""

import hmac
import hashlib
import json
import time
import requests
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)
FUTURES_BASE = "https://api.coindcx.com"
PUBLIC_BASE  = "https://public.coindcx.com"

def _sign(secret, body):
	json_body = json.dumps(body, separators=(",", ":"))
	return hmac.new(bytes(secret, encoding="utf-8"), json_body.encode(), hashlib.sha256).hexdigest()

def _headers(api_key, signature):
	return {"Content-Type": "application/json", "X-AUTH-APIKEY": api_key, "X-AUTH-SIGNATURE": signature}

class CoinDCXREST:
	def __init__(self, api_key, api_secret):
		self.key    = api_key
		self.secret = api_secret

	def _post(self, path, body):
		body["timestamp"] = int(time.time() * 1000)
		sig  = _sign(self.secret, body)
		resp = requests.post(FUTURES_BASE + path, headers=_headers(self.key, sig), json=body, timeout=10)
		resp.raise_for_status()
		return resp.json()

	def _get(self, path, body=None):
		if body is None:
			body = {}
		body["timestamp"] = int(time.time() * 1000)
		sig  = _sign(self.secret, body)
		resp = requests.get(FUTURES_BASE + path, headers=_headers(self.key, sig), json=body, timeout=10)
		resp.raise_for_status()
		return resp.json()

	def get_candles(self, pair, interval, limit=100):
		resp = requests.get(
			f"{PUBLIC_BASE}/market_data/candles",
			params={"pair": pair, "interval": interval, "limit": limit},
			timeout=10,
		)
		resp.raise_for_status()
		return resp.json()

	def get_active_instruments(self):
		resp = requests.get(f"{FUTURES_BASE}/exchange/v1/derivatives/futures/data/active_instruments", timeout=10)
		resp.raise_for_status()
		return resp.json()

	def get_wallet(self):
		"""Get futures wallet balance. Returns array of wallet objects."""
		# Official CoinDCX API endpoint from docs: https://docs.coindcx.com/#wallet-details
		path = "/exchange/v1/derivatives/futures/wallets"
		
		try:
			# Use GET method as per official docs
			payload = self._get(path)
			logger.info(f"Wallet API response: {payload}")
			return payload
		except (requests.HTTPError, requests.RequestException) as e:
			logger.error(f"Wallet API failed: {e}")
			return []

	def get_positions(self):
		return self._post("/exchange/v1/derivatives/futures/positions", {})

	def get_open_orders(self, pair=""):
		body = {}
		if pair:
			body["pair"] = pair
		return self._post("/exchange/v1/derivatives/futures/orders", body)

	def place_order(self, pair, side, order_type, quantity, price=0, leverage=1):
		body = {"pair": pair, "side": side, "order_type": order_type, "quantity": quantity, "leverage": leverage}
		if order_type == "limit_order":
			body["price"] = price
		return self._post("/exchange/v1/derivatives/futures/orders/create", body)

	def place_tp_sl(self, pair, position_id, tp_price, sl_price):
		body = {"pair": pair, "position_id": position_id, "tp_price": tp_price, "sl_price": sl_price}
		return self._post("/exchange/v1/derivatives/futures/orders/create_tp_sl", body)

	def cancel_order(self, order_id):
		return self._post("/exchange/v1/derivatives/futures/orders/cancel", {"id": order_id})

	def exit_position(self, position_id):
		return self._post("/exchange/v1/derivatives/futures/positions/exit", {"position_id": position_id})

	def get_trade_history(self, pair="", limit=50):
		body = {"limit": limit}
		if pair:
			body["pair"] = pair
		return self._post("/exchange/v1/derivatives/futures/trades", body)

class CoinDCXSocket:
	SOCKET_URL = "wss://stream.coindcx.com"

	def __init__(self, api_key, api_secret):
		import socketio as sio_module
		self.key    = api_key
		self.secret = api_secret
		self.sio    = sio_module.Client(logger=False, engineio_logger=False)
		self._callbacks = {}

	def on(self, event, fn):
		self._callbacks[event] = fn

	def _auth_payload(self):
		ts  = int(time.time() * 1000)
		sig = hmac.new(bytes(self.secret, encoding="utf-8"), str(ts).encode(), hashlib.sha256).hexdigest()
		return {"api_key": self.key, "timestamp": ts, "signature": sig}

	def connect(self, pair, interval="1m"):
		sio = self.sio

		@sio.event
		def connect():
			logger.info("Socket connected")
			sio.emit("join", self._auth_payload())
			sio.emit("join", {"channelName": f"candlestick@{pair}@{interval}"})
			sio.emit("join", {"channelName": f"ltp@futures@{pair}"})

		@sio.event
		def disconnect():
			logger.warning("Socket disconnected")

		for event, fn in self._callbacks.items():
			sio.on(event, fn)

		try:
			sio.connect(self.SOCKET_URL, transports=["websocket"], wait_timeout=10)
		except TypeError:
			sio.connect(self.SOCKET_URL, transports=["websocket"])

	def disconnect(self):
		self.sio.disconnect()

	def wait(self):
		self.sio.wait()
