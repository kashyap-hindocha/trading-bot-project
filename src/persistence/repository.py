from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ConfigKV, PerformanceMetric, Signal, Trade
from .database import session_scope


class Repository:
    def __init__(self, db: Session | None = None):
        self._own_session = db is None
        self.db = db or session_scope()

    def close(self) -> None:
        if self._own_session:
            self.db.close()

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # --- config ---
    def get_config(self, key: str, default: str | None = None) -> str | None:
        row = self.db.get(ConfigKV, key)
        return row.value if row else default

    def set_config(self, key: str, value: str) -> None:
        row = self.db.get(ConfigKV, key)
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            self.db.add(ConfigKV(key=key, value=value))
        self.db.commit()

    def get_trading_mode(self) -> str:
        return self.get_config("trading_mode", "paper") or "paper"

    def set_trading_mode(self, mode: str) -> None:
        self.set_config("trading_mode", mode)

    # --- trades ---
    def add_trade(
        self,
        *,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        leverage: int = 1,
        is_paper: bool = True,
        status: str = "open",
        pnl: float | None = None,
    ) -> Trade:
        t = Trade(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            leverage=leverage,
            pnl=pnl,
            is_paper=is_paper,
            status=status,
        )
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def list_trades(self, paper: bool | None = None, limit: int = 200) -> list[Trade]:
        q = select(Trade)
        if paper is not None:
            q = q.where(Trade.is_paper == paper)
        q = q.order_by(Trade.created_at.desc()).limit(limit)
        return list(self.db.scalars(q))

    def list_open_trades(self, *, is_paper: bool) -> list[Trade]:
        q = (
            select(Trade)
            .where(Trade.is_paper == is_paper, Trade.status == "open")
            .order_by(Trade.created_at.desc())
        )
        return list(self.db.scalars(q))

    def update_trade_status(
        self,
        trade_id: str,
        status: str,
        closed_at: datetime | None = None,
        pnl: float | None = None,
    ) -> None:
        row = self.db.scalar(select(Trade).where(Trade.trade_id == trade_id))
        if row:
            row.status = status
            if closed_at is not None:
                row.closed_at = closed_at
            if pnl is not None:
                row.pnl = pnl
            self.db.commit()

    def reconcile_paper_trades_not_in_memory(self, valid_trade_ids: set[str]) -> int:
        """Close paper rows in SQLite that are still `open` but not in `valid_trade_ids`.

        Runtime paper positions live in `PaperExecutor.positions`; after restart or pair change memory
        can be empty while SQLite still has `open` trades. This aligns the DB with in-memory truth.
        """
        now = datetime.now(timezone.utc)
        n = 0
        for t in self.list_open_trades(is_paper=True):
            if t.trade_id in valid_trade_ids:
                continue
            row = self.db.scalar(select(Trade).where(Trade.trade_id == t.trade_id))
            if row:
                row.status = "closed"
                row.closed_at = now
                row.pnl = None
                n += 1
        if n:
            self.db.commit()
        return n

    # --- signals ---
    def add_signal(
        self,
        *,
        symbol: str,
        signal_type: str,
        indicator_name: str | None = None,
        strength: float | None = None,
        indicator_values: dict[str, Any] | None = None,
    ) -> Signal:
        s = Signal(
            symbol=symbol,
            signal_type=signal_type,
            indicator_name=indicator_name,
            strength=strength,
            indicator_values=json.dumps(indicator_values) if indicator_values else None,
        )
        self.db.add(s)
        self.db.commit()
        self.db.refresh(s)
        return s

    def recent_signals(self, limit: int = 50) -> list[Signal]:
        q = select(Signal).order_by(Signal.timestamp.desc()).limit(limit)
        return list(self.db.scalars(q))

    def closed_trades_for_day(self, day: date, *, is_paper: bool) -> list[Trade]:
        start = datetime.combine(day, datetime.min.time())
        end = datetime.combine(day, datetime.max.time())
        q = (
            select(Trade)
            .where(
                Trade.is_paper == is_paper,
                Trade.status == "closed",
                Trade.closed_at >= start,
                Trade.closed_at <= end,
            )
            .order_by(Trade.closed_at.desc())
        )
        return list(self.db.scalars(q))

    # --- performance ---
    def upsert_performance(
        self,
        *,
        day: date,
        total_pnl: float | None,
        win_rate: float | None,
        sharpe_ratio: float | None,
        max_drawdown: float | None,
        trade_count: int | None,
        is_paper: bool,
    ) -> None:
        existing = self.db.scalar(
            select(PerformanceMetric).where(
                PerformanceMetric.date == day,
                PerformanceMetric.is_paper == is_paper,
            )
        )
        if existing:
            existing.total_pnl = total_pnl
            existing.win_rate = win_rate
            existing.sharpe_ratio = sharpe_ratio
            existing.max_drawdown = max_drawdown
            existing.trade_count = trade_count
        else:
            self.db.add(
                PerformanceMetric(
                    date=day,
                    total_pnl=total_pnl,
                    win_rate=win_rate,
                    sharpe_ratio=sharpe_ratio,
                    max_drawdown=max_drawdown,
                    trade_count=trade_count,
                    is_paper=is_paper,
                )
            )
        self.db.commit()
