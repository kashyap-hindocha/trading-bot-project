from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings
from src.persistence.repository import Repository
from src.trading.coindcx_client import CoinDCXClient
from src.utils.helpers import new_trade_id

logger = logging.getLogger(__name__)


class LiveExecutor:
    def __init__(self, settings: Settings, client: CoinDCXClient, repo: Repository) -> None:
        self.settings = settings
        self.client = client
        self.repo = repo

    def place_market(
        self,
        *,
        symbol: str,
        market: str,
        side: str,
        quantity: float,
        leverage: int,
        tp_price: float | None = None,
        sl_price: float | None = None,
        ecode: str | None = None,
    ) -> dict[str, Any]:
        if not self.settings.coindcx_api_key or not self.settings.coindcx_api_secret:
            return {"ok": False, "error": "missing_api_credentials"}

        tid = new_trade_id()
        try:
            raw = self.client.margin_create_market(
                market=market,
                side=side,
                quantity=quantity,
                leverage=float(leverage),
                target_price=tp_price,
                sl_price=sl_price,
                ecode=ecode,
            )
        except Exception as e:
            logger.exception("live order failed")
            return {"ok": False, "error": str(e)}

        px = 0.0
        if isinstance(raw, list) and raw:
            px = float(raw[0].get("price") or raw[0].get("avg_entry") or 0)
        self.repo.add_trade(
            trade_id=tid,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=px,
            leverage=leverage,
            is_paper=False,
            status="open",
        )
        return {"ok": True, "trade_id": tid, "exchange_response": raw}
