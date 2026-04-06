from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings
from src.data.data_manager import DataManager
from src.persistence.repository import Repository
from src.trading.live_executor import LiveExecutor
from src.trading.paper_executor import PaperExecutor
from src.trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        risk: RiskManager,
        paper: PaperExecutor,
        live: LiveExecutor,
        data: DataManager,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.risk = risk
        self.paper = paper
        self.live = live
        self.data = data

    def current_mode(self) -> str:
        return self.repo.get_trading_mode() or "paper"

    def set_mode(self, mode: str) -> None:
        self.repo.set_trading_mode(mode)

    def place_manual(
        self,
        *,
        symbol: str,
        market: str,
        side: str,
        quantity: float,
        leverage: int,
        tp_price: float | None,
        sl_price: float | None,
        ecode: str | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        market = market.strip().upper()
        side = side.lower().strip()
        if side not in ("buy", "sell"):
            return {"ok": False, "error": "invalid_side"}
        if quantity <= 0:
            return {"ok": False, "error": "invalid_quantity"}

        ltp = self.data.last_price(symbol) or 0.0
        if ltp <= 0:
            return {"ok": False, "error": "no_last_price"}

        mode = self.current_mode()
        is_paper = mode != "live"
        paper_open_positions = len(self.paper.positions) if is_paper else None
        rr = self.risk.check(
            self.repo,
            is_paper=is_paper,
            side=side,
            quantity=quantity,
            price=ltp,
            leverage=leverage,
            paper_open_positions=paper_open_positions,
        )
        if not rr.allowed:
            return {"ok": False, "error": rr.reason}

        if is_paper:
            out = self.paper.place_market(
                symbol=symbol,
                side=side,
                quantity=quantity,
                ltp=ltp,
                leverage=leverage,
                tp_price=tp_price,
                sl_price=sl_price,
            )
        else:
            out = self.live.place_market(
                symbol=symbol,
                market=market,
                side=side,
                quantity=quantity,
                leverage=leverage,
                tp_price=tp_price,
                sl_price=sl_price,
                ecode=ecode,
            )
        if out.get("ok"):
            self.risk.record_trade_executed()
        return out

    def on_signal(
        self,
        *,
        signal: str,
        symbol: str,
        market: str,
        quantity: float,
        leverage: int,
        ecode: str | None = None,
        tp_price: float | None = None,
        sl_price: float | None = None,
    ) -> dict[str, Any]:
        if signal not in ("buy", "sell"):
            return {"ok": False, "error": "bad_signal"}
        return self.place_manual(
            symbol=symbol,
            market=market,
            side=signal,
            quantity=quantity,
            leverage=leverage,
            tp_price=tp_price,
            sl_price=sl_price,
            ecode=ecode,
        )
