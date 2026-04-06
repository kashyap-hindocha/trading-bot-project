from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import requests

from config.settings import DEFAULT_ECODE, Settings

logger = logging.getLogger(__name__)


class CoinDCXClient:
    REST_BASE = "https://api.coindcx.com"

    def __init__(self, settings: Settings, rate_limiter=None) -> None:
        self.settings = settings
        self._limiter = rate_limiter
        self.session = requests.Session()

    def _sign_body(self, body: dict[str, Any]) -> tuple[str, str]:
        secret = self.settings.coindcx_api_secret.encode("utf-8")
        payload = json.dumps(body, separators=(",", ":"))
        sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return payload, sig

    def _post(self, path: str, body: dict[str, Any], retries: int = 4) -> Any:
        if self._limiter:
            self._limiter.acquire()
        body = {**body, "timestamp": int(round(time.time() * 1000))}
        payload, signature = self._sign_body(body)
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self.settings.coindcx_api_key,
            "X-AUTH-SIGNATURE": signature,
        }
        url = f"{self.REST_BASE}{path}"
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self.session.post(url, data=payload, headers=headers, timeout=30)
                data = r.json() if r.content else {}
                if r.status_code >= 400:
                    logger.warning("CoinDCX POST %s HTTP %s: %s", path, r.status_code, data)
                    if r.status_code in (429, 500, 502, 503) and attempt < retries:
                        time.sleep(delay)
                        delay *= 2
                        continue
                return data
            except Exception as e:
                last_err = e
                logger.exception("CoinDCX request error: %s", e)
                if attempt < retries:
                    time.sleep(delay)
                    delay *= 2
        if last_err:
            raise last_err
        return {}

    def margin_create_market(
        self,
        *,
        market: str,
        side: str,
        quantity: float,
        leverage: float,
        ecode: str | None = None,
        target_price: float | None = None,
        stop_price: float | None = None,
        sl_price: float | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "side": side,
            "order_type": "market_order",
            "market": market,
            "quantity": quantity,
            "leverage": float(leverage),
            "ecode": ecode or DEFAULT_ECODE,
        }
        if target_price is not None:
            body["target_price"] = target_price
        if stop_price is not None:
            body["stop_price"] = stop_price
        if sl_price is not None:
            body["sl_price"] = sl_price
        return self._post("/exchange/v1/margin/create", body)

    def margin_fetch_orders(self) -> Any:
        body: dict[str, Any] = {}
        return self._post("/exchange/v1/margin/fetch_orders", body)

    def margin_cancel(self, order_id: str) -> Any:
        body = {"id": order_id}
        return self._post("/exchange/v1/margin/cancel", body)
