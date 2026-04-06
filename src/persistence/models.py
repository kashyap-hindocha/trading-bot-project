from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.utcnow())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.utcnow())
    indicator_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    signal_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicator_values: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfigKV(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.utcnow(), onupdate=lambda: datetime.utcnow())


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    total_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_paper: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
