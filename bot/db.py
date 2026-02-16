"""
SQLite database — stores all trades, positions, and bot events.
"""

import sqlite3
import json
from datetime import datetime

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
            strategy_note TEXT
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
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()


# ── Trades ───────────────────────────────────
def insert_trade(pair, side, entry_price, quantity, leverage, tp_price, sl_price,
                 order_id="", position_id="", strategy_note=""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO trades
            (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
             order_id, position_id, opened_at, strategy_note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
          order_id, position_id, datetime.utcnow().isoformat(), strategy_note))
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
def log_event(level: str, message: str):
    conn = get_conn()
    conn.execute("INSERT INTO bot_log (level, message) VALUES (?,?)", (level, message))
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


def upsert_pair_config(pair: str, enabled: int, leverage: int, quantity: float):
    """Insert or update pair configuration."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO pair_config (pair, enabled, leverage, quantity, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(pair) DO UPDATE SET
            enabled=excluded.enabled,
            leverage=excluded.leverage,
            quantity=excluded.quantity,
            updated_at=datetime('now')
    """, (pair, enabled, leverage, quantity))
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
