from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from config.settings import DEFAULT_BOOTSTRAP_MARKET, Settings
from src.persistence.models import Trade
from src.persistence.repository import Repository


@dataclass
class RiskResult:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_trade_ts: datetime | None = None

    def record_trade_executed(self) -> None:
        self._last_trade_ts = datetime.now(timezone.utc)

    def daily_realized_pnl(self, repo: Repository, *, is_paper: bool) -> float:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        q = select(func.coalesce(func.sum(Trade.pnl), 0.0)).where(
            Trade.is_paper == is_paper,
            Trade.status == "closed",
            Trade.closed_at >= start,
            Trade.pnl.is_not(None),
        )
        v = repo.db.scalar(q)
        return float(v or 0.0)

    def open_positions_count(self, repo: Repository, *, is_paper: bool) -> int:
        q = select(func.count()).select_from(Trade).where(
            Trade.is_paper == is_paper,
            Trade.status == "open",
        )
        return int(repo.db.scalar(q) or 0)

    def check(
        self,
        repo: Repository,
        *,
        is_paper: bool,
        side: str,
        quantity: float,
        price: float,
        leverage: int,
        market_symbol: str | None = None,
        paper_open_positions: int | None = None,
    ) -> RiskResult:
        """paper_open_positions: when set in paper mode, use this count (in-memory truth) instead of SQLite.

        SQLite can hold stale `open` rows after pair reset or restart while `PaperExecutor.positions` is empty;
        counting DB rows alone caused max_open_positions to block with 0 rows shown in the UI.
        """
        if self._last_trade_ts:
            delta = (datetime.now(timezone.utc) - self._last_trade_ts).total_seconds()
            if delta < self.settings.min_time_between_trades_sec:
                return RiskResult(False, "min_time_between_trades")

        dpnl = self.daily_realized_pnl(repo, is_paper=is_paper)
        if dpnl <= -abs(self.settings.daily_loss_limit):
            return RiskResult(False, "daily_loss_limit")

        if is_paper and paper_open_positions is not None:
            opens = paper_open_positions
        else:
            opens = self.open_positions_count(repo, is_paper=is_paper)
        if opens >= self.settings.max_open_positions:
            return RiskResult(False, "max_open_positions")

        notional = abs(quantity * price)
        ms = (market_symbol or DEFAULT_BOOTSTRAP_MARKET).strip().upper()
        if ms.startswith("BTC") and quantity > self.settings.max_position_size_btc:
            return RiskResult(False, "max_position_size")

        if leverage < 1 or leverage > 20:
            return RiskResult(False, "leverage_out_of_range")

        _ = side
        _ = notional
        return RiskResult(True, "")
