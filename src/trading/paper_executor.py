from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings
from src.persistence.repository import Repository
from src.utils.helpers import new_trade_id

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    trade_id: str
    symbol: str
    side: str
    quantity: float
    entry: float
    leverage: int
    tp_price: float | None
    sl_price: float | None


class PaperExecutor:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self.virtual_balance = settings.paper_trading_balance
        self.positions: dict[str, PaperPosition] = {}

    def _apply_slippage(self, price: float, side: str) -> float:
        p = self.settings.slippage_percent / 100.0
        if side == "buy":
            return price * (1 + p)
        return price * (1 - p)

    def _fee(self, notional: float) -> float:
        return notional * (self.settings.taker_fee_percent / 100.0)

    def on_price(self, symbol: str, ltp: float) -> list[str]:
        """Check TP/SL; return list of closed trade_ids."""
        closed: list[str] = []
        for tid, pos in list(self.positions.items()):
            if pos.symbol != symbol:
                continue
            hit = None
            exit_price = ltp
            if pos.side == "buy":
                if pos.tp_price and ltp >= pos.tp_price:
                    hit = "tp"
                    exit_price = pos.tp_price
                elif pos.sl_price and ltp <= pos.sl_price:
                    hit = "sl"
                    exit_price = pos.sl_price
            else:
                if pos.tp_price and ltp <= pos.tp_price:
                    hit = "tp"
                    exit_price = pos.tp_price
                elif pos.sl_price and ltp >= pos.sl_price:
                    hit = "sl"
                    exit_price = pos.sl_price
            if hit:
                pnl = self._close_position(pos, exit_price, hit)
                self.repo.update_trade_status(
                    tid,
                    "closed",
                    closed_at=datetime.now(timezone.utc),
                    pnl=pnl,
                )
                del self.positions[tid]
                closed.append(tid)
        return closed

    def _close_position(self, pos: PaperPosition, exit_price: float, reason: str) -> float:
        notional_entry = abs(pos.entry * pos.quantity)
        margin = notional_entry / max(pos.leverage, 1)
        if pos.side == "buy":
            pnl = (exit_price - pos.entry) * pos.quantity
        else:
            pnl = (pos.entry - exit_price) * pos.quantity
        fee_close = self._fee(abs(exit_price * pos.quantity))
        self.virtual_balance += margin + pnl - fee_close
        logger.info("paper close %s %s pnl=%.5f (%s)", pos.trade_id, pos.symbol, pnl, reason)
        return pnl

    def close_at_market(self, *, trade_id: str, ltp: float) -> dict[str, Any]:
        """Close an open paper position at current LTP (opposite side with slippage)."""
        pos = self.positions.get(trade_id)
        if not pos:
            return {"ok": False, "error": "position_not_found"}
        if ltp <= 0:
            return {"ok": False, "error": "no_last_price"}
        if pos.side == "buy":
            exit_fill = self._apply_slippage(ltp, "sell")
        else:
            exit_fill = self._apply_slippage(ltp, "buy")
        pnl = self._close_position(pos, exit_fill, "manual")
        self.repo.update_trade_status(
            trade_id,
            "closed",
            closed_at=datetime.now(timezone.utc),
            pnl=pnl,
        )
        del self.positions[trade_id]
        return {"ok": True, "trade_id": trade_id, "exit_price": exit_fill, "pnl": pnl}

    def place_market(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        ltp: float,
        leverage: int,
        tp_price: float | None = None,
        sl_price: float | None = None,
    ) -> dict[str, Any]:
        fill = self._apply_slippage(ltp, side)
        notional = abs(quantity * fill)
        fee = self._fee(notional)
        margin = notional / max(leverage, 1)

        if margin + fee > self.virtual_balance:
            return {"ok": False, "error": "insufficient_virtual_balance"}

        tid = new_trade_id()
        self.virtual_balance -= margin + fee

        self.repo.add_trade(
            trade_id=tid,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=fill,
            leverage=leverage,
            is_paper=True,
            status="open",
        )
        self.positions[tid] = PaperPosition(
            trade_id=tid,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry=fill,
            leverage=leverage,
            tp_price=tp_price,
            sl_price=sl_price,
        )
        return {"ok": True, "trade_id": tid, "fill_price": fill}

    def open_positions_view(self) -> list[dict[str, Any]]:
        out = []
        for p in self.positions.values():
            out.append(
                {
                    "trade_id": p.trade_id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "quantity": p.quantity,
                    "entry": p.entry,
                    "leverage": p.leverage,
                    "tp_price": p.tp_price,
                    "sl_price": p.sl_price,
                }
            )
        return out
