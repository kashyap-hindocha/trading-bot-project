import os


def bot_home() -> str:
    """
    Base directory for this project on the server.
    Defaults to the repo root (parent of bot/).
    """
    default_home = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.abspath(os.getenv("BOT_HOME", default_home))


def data_dir() -> str:
    """Directory for DB + logs. Defaults to $BOT_HOME/data."""
    return os.path.abspath(os.getenv("BOT_DATA_DIR", os.path.join(bot_home(), "data")))


def env_file() -> str:
    """dotenv file path. Defaults to $BOT_HOME/.env."""
    return os.path.abspath(os.getenv("BOT_ENV_FILE", os.path.join(bot_home(), ".env")))


def db_path() -> str:
    """SQLite DB path. Defaults to $BOT_DATA_DIR/bot.db."""
    return os.path.abspath(os.getenv("BOT_DB_PATH", os.path.join(data_dir(), "bot.db")))


def bot_log_path() -> str:
    """Main bot log path used by bot/main.py and server log tail API."""
    return os.path.abspath(os.getenv("BOT_LOG_PATH", os.path.join(data_dir(), "bot.log")))


def bot_manager_log_path() -> str:
    return os.path.abspath(os.getenv("BOT_MANAGER_LOG_PATH", os.path.join(data_dir(), "bot_manager.log")))


def entry_order_mode() -> str:
    """
    REAL entry behavior:
    - LIMIT: existing behavior (limit order at current price)
    - MARKET: market order (if exchange supports)
    - LIMIT_THEN_MARKET: try limit, if not filled within ttl, cancel and place market
    """
    return str(os.getenv("BOT_ENTRY_ORDER_MODE", "LIMIT")).upper()


def entry_limit_ttl_sec() -> float:
    """Seconds to wait for a limit entry to become a position in LIMIT_THEN_MARKET."""
    raw = os.getenv("BOT_ENTRY_LIMIT_TTL_SEC", "5")
    try:
        return max(0.5, float(raw))
    except Exception:
        return 5.0


def position_reconcile_interval_sec() -> float:
    """How often to reconcile DB open trades vs exchange positions."""
    raw = os.getenv("BOT_POSITION_RECONCILE_SEC", "30")
    try:
        return max(10.0, float(raw))
    except Exception:
        return 30.0

