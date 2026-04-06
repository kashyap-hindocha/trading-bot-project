"""Application settings loaded from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

# First-boot / offline fallback before SQLite `active_pair` exists (see dashboard pair picker).
DEFAULT_BOOTSTRAP_MARKET = "BTCUSDT"
DEFAULT_COINDCX_PAIR = "KC-BTC_USDT"
DEFAULT_ECODE = "KC"
DEFAULT_BINANCE_SYMBOL = "BTCUSDT"
DEFAULT_TRADINGVIEW_SYMBOL = "BINANCE:BTCUSDT"


@dataclass(frozen=True)
class Settings:
    coindcx_api_key: str
    coindcx_api_secret: str
    paper_trading_balance: float
    default_leverage: int
    max_position_size_btc: float
    daily_loss_limit: float
    max_open_positions: int
    min_time_between_trades_sec: int
    log_level: str
    slippage_percent: float
    web_port: int
    database_url: str
    maker_fee_percent: float = 0.02
    taker_fee_percent: float = 0.05
    order_rate_limit: int = 2000
    order_rate_window_sec: int = 60
    ws_max_retries: int = 5
    ws_backoff_base_sec: float = 1.0
    default_order_quantity: float = 0.001
    auto_trade_enabled: bool = True
    # CoinDCX public candles are often stale; auto can switch OHLC/LTP to Binance (per active pair).
    ohlc_source: str = "auto"
    coindcx_max_candle_age_sec: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings(
        coindcx_api_key=os.getenv("COINDCX_API_KEY", ""),
        coindcx_api_secret=os.getenv("COINDCX_API_SECRET", ""),
        paper_trading_balance=float(os.getenv("PAPER_TRADING_BALANCE", "10000")),
        default_leverage=int(os.getenv("DEFAULT_LEVERAGE", "5")),
        max_position_size_btc=float(os.getenv("MAX_POSITION_SIZE_BTC", "0.5")),
        daily_loss_limit=float(os.getenv("DAILY_LOSS_LIMIT", "500")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
        min_time_between_trades_sec=int(os.getenv("MIN_TIME_BETWEEN_TRADES_SEC", "10")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        slippage_percent=float(os.getenv("SLIPPAGE_PERCENT", "0.05")),
        web_port=int(os.getenv("WEB_PORT", "8000")),
        database_url=os.getenv("DATABASE_URL", "sqlite:///data/trading.db"),
        default_order_quantity=float(os.getenv("DEFAULT_ORDER_QUANTITY", "0.001")),
        auto_trade_enabled=os.getenv("AUTO_TRADE_ENABLED", "true").lower() in ("1", "true", "yes"),
        ohlc_source=os.getenv("OHLC_SOURCE", "auto").strip().lower(),
        coindcx_max_candle_age_sec=int(os.getenv("COINDCX_MAX_CANDLE_AGE_SEC", "180")),
    )
