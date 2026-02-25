"""
SQLite database — stores all trades, positions, and bot events.
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional

DB_PATH = "/home/ubuntu/trading-bot/data/bot.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pair          TEXT NOT NULL,
            side          TEXT NOT NULL,       -- buy / sell
            entry_price   REAL,
            exit_price    REAL,
            quantity      REAL,
            leverage      INTEGER,
            tp_price      REAL,
            sl_price      REAL,
            pnl           REAL,
            status        TEXT DEFAULT 'open', -- open / closed / cancelled
            order_id      TEXT,
            position_id   TEXT,
            opened_at     TEXT,
            closed_at     TEXT,
            strategy_name TEXT DEFAULT 'enhanced_v2', -- Strategy used for this trade
            strategy_note TEXT,
            confidence    REAL DEFAULT 0.0,    -- strategy confidence % (0-100)
            atr           REAL DEFAULT 0.0,    -- Average True Range at entry
            position_size REAL DEFAULT 0.0,    -- Dynamic position size in base currency
            trailing_stop REAL DEFAULT 0.0     -- ATR-based trailing stop level
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            level      TEXT,   -- INFO / WARNING / ERROR
            message    TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            balance    REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS pair_config (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            pair       TEXT UNIQUE NOT NULL,
            enabled    INTEGER DEFAULT 0,   -- 0=disabled, 1=enabled
            leverage   INTEGER DEFAULT 5,
            quantity   REAL DEFAULT 0.001,
            inr_amount REAL DEFAULT 300.0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Backfill existing DBs missing inr_amount column
    cols = {row[1] for row in c.execute("PRAGMA table_info(pair_config)").fetchall()}
    if "inr_amount" not in cols:
        c.execute("ALTER TABLE pair_config ADD COLUMN inr_amount REAL DEFAULT 300.0")
        c.execute("UPDATE pair_config SET inr_amount=300.0 WHERE inr_amount IS NULL")
    if "auto_enabled" not in cols:
        c.execute("ALTER TABLE pair_config ADD COLUMN auto_enabled INTEGER DEFAULT 0")
        c.execute("UPDATE pair_config SET auto_enabled=0 WHERE auto_enabled IS NULL")
    if "enabled_by_strategy" not in cols:
        c.execute("ALTER TABLE pair_config ADD COLUMN enabled_by_strategy TEXT")
    if "enabled_at_confidence" not in cols:
        c.execute("ALTER TABLE pair_config ADD COLUMN enabled_at_confidence REAL")

    # Per-pair execution status (last run: signal, confidence, error) for UI
    c.execute("""
        CREATE TABLE IF NOT EXISTS pair_execution_status (
            pair             TEXT PRIMARY KEY,
            last_closed_at   TEXT,
            last_signal      TEXT,
            last_confidence  REAL,
            last_error       TEXT,
            updated_at       TEXT DEFAULT (datetime('now'))
        )
    """)

    # Add new strategy metric columns to trades table
    trade_cols = {row[1] for row in c.execute("PRAGMA table_info(trades)").fetchall()}
    if "atr" not in trade_cols:
        c.execute("ALTER TABLE trades ADD COLUMN atr REAL DEFAULT 0.0")
    if "position_size" not in trade_cols:
        c.execute("ALTER TABLE trades ADD COLUMN position_size REAL DEFAULT 0.0")
    if "trailing_stop" not in trade_cols:
        c.execute("ALTER TABLE trades ADD COLUMN trailing_stop REAL DEFAULT 0.0")
    if "strategy_name" not in trade_cols:
        c.execute("ALTER TABLE trades ADD COLUMN strategy_name TEXT DEFAULT 'enhanced_v2'")
    
    # Add new strategy metric columns to paper_trades table (for DBs created before these columns existed)
    paper_cols = {row[1] for row in c.execute("PRAGMA table_info(paper_trades)").fetchall()}
    if "confidence" not in paper_cols:
        c.execute("ALTER TABLE paper_trades ADD COLUMN confidence REAL DEFAULT 0.0")
    if "atr" not in paper_cols:
        c.execute("ALTER TABLE paper_trades ADD COLUMN atr REAL DEFAULT 0.0")
    if "position_size" not in paper_cols:
        c.execute("ALTER TABLE paper_trades ADD COLUMN position_size REAL DEFAULT 0.0")
    if "trailing_stop" not in paper_cols:
        c.execute("ALTER TABLE paper_trades ADD COLUMN trailing_stop REAL DEFAULT 0.0")
    if "strategy_name" not in paper_cols:
        c.execute("ALTER TABLE paper_trades ADD COLUMN strategy_name TEXT DEFAULT 'enhanced_v2'")

    c.execute("""
        CREATE TABLE IF NOT EXISTS trading_mode (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            mode       TEXT NOT NULL,  -- REAL / PAPER
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_wallet (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            balance    REAL,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pair          TEXT NOT NULL,
            side          TEXT NOT NULL,       -- buy / sell
            entry_price   REAL,
            exit_price    REAL,
            quantity      REAL,
            leverage      INTEGER,
            tp_price      REAL,
            sl_price      REAL,
            pnl           REAL,
            fee_paid      REAL,
            status        TEXT DEFAULT 'open', -- open / closed / cancelled
            order_id      TEXT,
            position_id   TEXT,
            opened_at     TEXT,
            closed_at     TEXT,
            strategy_name TEXT DEFAULT 'enhanced_v2', -- Strategy used for this trade
            strategy_note TEXT,
            confidence    REAL DEFAULT 0.0,    -- strategy confidence % (0-100)
            atr           REAL DEFAULT 0.0,    -- Average True Range at entry
            position_size REAL DEFAULT 0.0,    -- Dynamic position size in base currency
            trailing_stop REAL DEFAULT 0.0     -- ATR-based trailing stop level
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            balance    REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            id                   INTEGER PRIMARY KEY CHECK (id = 1),
            pair_mode            TEXT DEFAULT 'MULTI',
            selected_pair        TEXT,
            active_strategy      TEXT DEFAULT 'enhanced_v2',   -- User-chosen strategy
            confidence_threshold REAL DEFAULT 80.0,            -- Min confidence % to execute (user-set)
            updated_at           TEXT DEFAULT (datetime('now'))
        )
    """)
    # Add new columns if missing (migration for existing DBs)
    bc_cols = {row[1] for row in c.execute("PRAGMA table_info(bot_config)").fetchall()}
    if "active_strategy" not in bc_cols:
        c.execute("ALTER TABLE bot_config ADD COLUMN active_strategy TEXT DEFAULT 'enhanced_v2'")
        c.execute("UPDATE bot_config SET active_strategy='enhanced_v2' WHERE active_strategy IS NULL")
    if "confidence_threshold" not in bc_cols:
        c.execute("ALTER TABLE bot_config ADD COLUMN confidence_threshold REAL DEFAULT 80.0")
        c.execute("UPDATE bot_config SET confidence_threshold=80.0 WHERE confidence_threshold IS NULL")

    c.execute("""
        INSERT OR IGNORE INTO bot_config (id, pair_mode, active_strategy, confidence_threshold)
        VALUES (1, 'MULTI', 'enhanced_v2', 80.0)
    """)

    conn.commit()
    conn.close()


# ── Trades ───────────────────────────────────
def insert_trade(pair, side, entry_price, quantity, leverage, tp_price, sl_price,
                 order_id="", position_id="", strategy_name="enhanced_v2", strategy_note="", confidence=0.0,
                 atr=0.0, position_size=0.0, trailing_stop=0.0):
    conn = get_conn()
    conn.execute("""
        INSERT INTO trades
            (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
             order_id, position_id, opened_at, strategy_name, strategy_note, confidence, atr, position_size, trailing_stop)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
          order_id, position_id, datetime.utcnow().isoformat(), strategy_name, strategy_note, confidence,
          atr, position_size, trailing_stop))
    conn.commit()
    conn.close()


def close_trade(position_id, exit_price, pnl):
    conn = get_conn()
    conn.execute("""
        UPDATE trades
        SET exit_price=?, pnl=?, status='closed', closed_at=?
        WHERE position_id=?
    """, (exit_price, pnl, datetime.utcnow().isoformat(), position_id))
    conn.commit()
    conn.close()


def get_open_trades():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_closed_trade_closed_at(pair: str, paper: bool = False) -> Optional[str]:
    """Return closed_at (ISO str) of the most recent closed trade for this pair, or None. Used for re-entry cooldown."""
    conn = get_conn()
    table = "paper_trades" if paper else "trades"
    row = conn.execute(
        f"SELECT closed_at FROM {table} WHERE pair=? AND status='closed' ORDER BY closed_at DESC LIMIT 1",
        (pair,),
    ).fetchone()
    conn.close()
    return row["closed_at"] if row and row["closed_at"] else None


def get_all_trades(limit=100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade_stats():
    conn = get_conn()
    rows = conn.execute(
        "SELECT pnl, status FROM trades WHERE status='closed'"
    ).fetchall()
    conn.close()

    closed = [dict(r) for r in rows]
    if not closed:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl": 0, "avg_pnl": 0}

    wins   = [t for t in closed if t["pnl"] and t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] and t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in closed if t["pnl"])

    return {
        "total":    len(closed),
        "wins":     len(wins),
        "losses":   len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "total_pnl": round(total_pnl, 4),
        "avg_pnl":   round(total_pnl / len(closed), 4) if closed else 0,
    }


# ── Equity snapshots ─────────────────────────
def snapshot_equity(balance: float):
    conn = get_conn()
    conn.execute("INSERT INTO equity_snapshots (balance) VALUES (?)", (balance,))
    conn.commit()
    conn.close()


def get_equity_history(limit=200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT balance, created_at FROM equity_snapshots ORDER BY created_at ASC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Bot log ──────────────────────────────────
BOT_LOG_RETENTION_DAYS = 2  # Keep only last 2 days (trade histories in trades/paper_trades are kept)


def log_event(level: str, message: str):
    conn = get_conn()
    conn.execute("INSERT INTO bot_log (level, message) VALUES (?,?)", (level, message))
    conn.commit()
    conn.close()


def cleanup_bot_log_older_than_days(days: int = None):
    """Delete bot_log entries older than the given days (default BOT_LOG_RETENTION_DAYS). Trade histories are not touched."""
    if days is None:
        days = BOT_LOG_RETENTION_DAYS
    conn = get_conn()
    conn.execute("DELETE FROM bot_log WHERE created_at < datetime('now', ?)", (f"-{days} days",))
    conn.commit()
    conn.close()


def get_recent_logs(limit=50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bot_log ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Pair Config ──────────────────────────────
def get_pair_config(pair: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM pair_config WHERE pair=?", (pair,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_pair_configs():
    """Get all pair configurations."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM pair_config ORDER BY pair ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_enabled_pairs():
    """Get only enabled pair configurations."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM pair_config WHERE enabled=1 ORDER BY pair ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_pair_config(pair: str, enabled: int, leverage: int, quantity: float, inr_amount: float):
    """Insert or update pair configuration."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO pair_config (pair, enabled, leverage, quantity, inr_amount, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(pair) DO UPDATE SET
            enabled=excluded.enabled,
            leverage=excluded.leverage,
            quantity=excluded.quantity,
            inr_amount=excluded.inr_amount,
            updated_at=datetime('now')
    """, (pair, enabled, leverage, quantity, inr_amount))
    conn.commit()
    conn.close()


def update_pair_enabled(pair: str, enabled: int):
    """Toggle pair enabled/disabled status."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO pair_config (pair, enabled, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(pair) DO UPDATE SET
            enabled=excluded.enabled,
            updated_at=datetime('now')
    """, (pair, enabled))
    conn.commit()
    conn.close()


def upsert_pair_execution_status(pair: str, last_closed_at: Optional[str] = None,
                                  last_signal: Optional[str] = None, last_confidence: Optional[float] = None,
                                  last_error: Optional[str] = None):
    """Update execution status for a pair (bot calls on closed candle / skip / execute)."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO pair_execution_status (pair, last_closed_at, last_signal, last_confidence, last_error, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(pair) DO UPDATE SET
            last_closed_at=COALESCE(excluded.last_closed_at, last_closed_at),
            last_signal=COALESCE(excluded.last_signal, last_signal),
            last_confidence=COALESCE(excluded.last_confidence, last_confidence),
            last_error=excluded.last_error,
            updated_at=datetime('now')
    """, (pair, last_closed_at, last_signal, last_confidence, last_error))
    conn.commit()
    conn.close()


def get_pair_execution_status_all():
    """Get last_closed_at, last_error etc. for all pairs (for UI)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT pair, last_closed_at, last_signal, last_confidence, last_error, updated_at FROM pair_execution_status"
    ).fetchall()
    conn.close()
    return {r["pair"]: dict(r) for r in rows}


# ── Trading mode ────────────────────────────
def get_trading_mode() -> str:
    conn = get_conn()
    row = conn.execute("SELECT mode FROM trading_mode WHERE id=1").fetchone()
    conn.close()
    return row["mode"] if row and row["mode"] else "REAL"


def set_trading_mode(mode: str):
    mode = mode.upper()
    conn = get_conn()
    conn.execute("""
        INSERT INTO trading_mode (id, mode, updated_at)
        VALUES (1, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            mode=excluded.mode,
            updated_at=datetime('now')
    """, (mode,))
    conn.commit()
    conn.close()


# ── Paper wallet ────────────────────────────
def get_paper_wallet_balance():
    conn = get_conn()
    row = conn.execute("SELECT balance FROM paper_wallet WHERE id=1").fetchone()
    conn.close()
    return row["balance"] if row and row["balance"] is not None else None


def set_paper_wallet_balance(balance: float):
    conn = get_conn()
    conn.execute("""
        INSERT INTO paper_wallet (id, balance, updated_at)
        VALUES (1, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            balance=excluded.balance,
            updated_at=datetime('now')
    """, (balance,))
    conn.commit()
    conn.close()


def init_paper_wallet_if_missing(balance: float):
    current = get_paper_wallet_balance()
    if current is None or current <= 0:
        set_paper_wallet_balance(balance)


# ── Paper trades ────────────────────────────
def insert_paper_trade(pair, side, entry_price, quantity, leverage, tp_price, sl_price,
                       fee_paid=0.0, order_id="", position_id="", strategy_name="enhanced_v2", strategy_note="", confidence=0.0,
                       atr=0.0, position_size=0.0, trailing_stop=0.0):
    conn = get_conn()
    conn.execute("""
        INSERT INTO paper_trades
            (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
             fee_paid, order_id, position_id, opened_at, strategy_name, strategy_note, confidence, atr, position_size, trailing_stop)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
          fee_paid, order_id, position_id, datetime.utcnow().isoformat(), strategy_name, strategy_note, confidence,
          atr, position_size, trailing_stop))
    conn.commit()
    conn.close()


def close_paper_trade(position_id, exit_price, pnl, fee_paid=0.0):
    conn = get_conn()
    conn.execute("""
        UPDATE paper_trades
        SET exit_price=?, pnl=?, fee_paid=?, status='closed', closed_at=?
        WHERE position_id=?
    """, (exit_price, pnl, fee_paid, datetime.utcnow().isoformat(), position_id))
    conn.commit()
    conn.close()


def get_open_paper_trades():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM paper_trades WHERE status='open'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_paper_trades(limit=100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM paper_trades ORDER BY opened_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_paper_trade_stats():
    conn = get_conn()
    rows = conn.execute(
        "SELECT pnl, status FROM paper_trades WHERE status='closed'"
    ).fetchall()
    conn.close()

    closed = [dict(r) for r in rows]
    if not closed:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl": 0, "avg_pnl": 0}

    wins   = [t for t in closed if t["pnl"] and t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] and t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in closed if t["pnl"])

    return {
        "total":    len(closed),
        "wins":     len(wins),
        "losses":   len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "total_pnl": round(total_pnl, 4),
        "avg_pnl":   round(total_pnl / len(closed), 4) if closed else 0,
    }


# ── Paper equity snapshots ──────────────────
def snapshot_paper_equity(balance: float):
    conn = get_conn()
    conn.execute("INSERT INTO paper_equity_snapshots (balance) VALUES (?)", (balance,))
    conn.commit()
    conn.close()


def get_paper_equity_history(limit=200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT balance, created_at FROM paper_equity_snapshots ORDER BY created_at ASC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Bot Config (Pair Mode) ──────────────────
def get_pair_mode() -> dict:
    """Get current pair mode (SINGLE/MULTI) and selected pair."""
    conn = get_conn()
    row = conn.execute("SELECT pair_mode, selected_pair FROM bot_config WHERE id=1").fetchone()
    conn.close()
    
    if row:
        return {
            "pair_mode": row["pair_mode"] or "MULTI",
            "selected_pair": row["selected_pair"]
        }
    
    # Default to MULTI mode if not set
    return {"pair_mode": "MULTI", "selected_pair": None}


def set_pair_mode(mode: str, selected_pair: str = None):
    """Set pair mode. Only MULTI is used: one bot process per enabled pair, max 3 open trades total."""
    mode = mode.upper()
    if mode == "SINGLE":
        mode = "MULTI"
    conn = get_conn()
    conn.execute("""
        INSERT INTO bot_config (id, pair_mode, selected_pair, updated_at)
        VALUES (1, ?, NULL, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            pair_mode=excluded.pair_mode,
            selected_pair=NULL,
            updated_at=datetime('now')
    """, (mode,))
    conn.commit()
    conn.close()


def get_active_strategy() -> str:
    conn = get_conn()
    row = conn.execute("SELECT active_strategy FROM bot_config WHERE id=1").fetchone()
    conn.close()
    return (row["active_strategy"] or "enhanced_v2") if row else "enhanced_v2"


def set_active_strategy(strategy_key: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO bot_config (id, active_strategy, updated_at) VALUES (1, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET active_strategy=excluded.active_strategy, updated_at=datetime('now')
    """, (strategy_key or "enhanced_v2",))
    conn.commit()
    conn.close()


def get_confidence_threshold() -> float:
    conn = get_conn()
    row = conn.execute("SELECT confidence_threshold FROM bot_config WHERE id=1").fetchone()
    conn.close()
    if row and row["confidence_threshold"] is not None:
        return float(row["confidence_threshold"])
    return 80.0


def set_confidence_threshold(threshold: float):
    conn = get_conn()
    conn.execute("""
        INSERT INTO bot_config (id, confidence_threshold, updated_at) VALUES (1, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET confidence_threshold=excluded.confidence_threshold, updated_at=datetime('now')
    """, (float(threshold),))
    conn.commit()
    conn.close()


def init_pair_mode_if_missing():
    """Initialize pair mode to MULTI if not set."""
    current = get_pair_mode()
    if not current or not current.get("pair_mode"):
        set_pair_mode("MULTI")
