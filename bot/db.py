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
            strategy_note TEXT,
            confidence    REAL DEFAULT 0.0    -- strategy confidence % (0-100)
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
            strategy_note TEXT,
            confidence    REAL DEFAULT 0.0    -- strategy confidence % (0-100)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            balance    REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()


# ── Trades ───────────────────────────────────
def insert_trade(pair, side, entry_price, quantity, leverage, tp_price, sl_price,
                 order_id="", position_id="", strategy_note="", confidence=0.0):
    conn = get_conn()
    conn.execute("""
        INSERT INTO trades
            (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
             order_id, position_id, opened_at, strategy_note, confidence)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
          order_id, position_id, datetime.utcnow().isoformat(), strategy_note, confidence))
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
                       fee_paid=0.0, order_id="", position_id="", strategy_note="", confidence=0.0):
    conn = get_conn()
    conn.execute("""
        INSERT INTO paper_trades
            (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
             fee_paid, order_id, position_id, opened_at, strategy_note, confidence)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (pair, side, entry_price, quantity, leverage, tp_price, sl_price,
          fee_paid, order_id, position_id, datetime.utcnow().isoformat(), strategy_note, confidence))
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
