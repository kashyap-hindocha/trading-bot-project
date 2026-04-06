from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from src.core.engine import TradingEngine
from src.persistence.repository import Repository

logger = logging.getLogger(__name__)


def _rollup_day(repo: Repository, *, is_paper: bool, day: date) -> None:
    trades = repo.closed_trades_for_day(day, is_paper=is_paper)
    if not trades:
        repo.upsert_performance(
            day=day,
            total_pnl=0.0,
            win_rate=None,
            sharpe_ratio=None,
            max_drawdown=None,
            trade_count=0,
            is_paper=is_paper,
        )
        return
    pnls = [float(t.pnl or 0) for t in trades]
    total = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / len(pnls) if pnls else None
    repo.upsert_performance(
        day=day,
        total_pnl=total,
        win_rate=win_rate,
        sharpe_ratio=None,
        max_drawdown=None,
        trade_count=len(trades),
        is_paper=is_paper,
    )


def start_scheduler(engine: TradingEngine) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=timezone.utc)

    def job() -> None:
        with Repository() as repo:
            today_utc = datetime.now(timezone.utc).date()
            yesterday = today_utc - timedelta(days=1)
            _rollup_day(repo, is_paper=True, day=yesterday)
            _rollup_day(repo, is_paper=False, day=yesterday)
        logger.info("Performance rollup completed")

    sched.add_job(job, "cron", hour=0, minute=5, timezone=timezone.utc)
    sched.start()
    return sched
