"""
CooperCorp PRJ-002 — Signal-to-Outcome SQLite Database
Tracks every scan signal and its eventual trade outcome for ML-driven threshold tuning.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "signals.db"


def init_db():
    """Initialize database and create tables if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            pre_score REAL,
            agent_scores_json TEXT,
            final_score REAL,
            conviction INTEGER,
            entered INTEGER DEFAULT 0,
            entry_price REAL,
            entry_time TEXT
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            exit_price REAL,
            exit_time TEXT,
            pnl_pct REAL,
            exit_reason TEXT,
            win INTEGER,
            FOREIGN KEY(signal_id) REFERENCES signals(id)
        );
        CREATE TABLE IF NOT EXISTS ticker_stats (
            ticker TEXT PRIMARY KEY,
            total_signals INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            avg_pnl REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            avg_score_wins REAL DEFAULT 0,
            avg_score_losses REAL DEFAULT 0,
            last_updated TEXT
        );
    """)
    conn.commit()
    conn.close()


def _get_conn():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_signal(ticker: str, pre_score: float, final_score: float, conviction: int,
               agent_scores: Optional[dict] = None) -> int:
    """Log a scan signal. Returns the signal_id."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO signals (ticker, timestamp, pre_score, agent_scores_json, final_score, conviction)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            datetime.now(timezone.utc).isoformat(),
            pre_score,
            json.dumps(agent_scores or {}),
            final_score,
            conviction
        ))
        signal_id = c.lastrowid
        conn.commit()
        conn.close()
        return signal_id
    except Exception as e:
        print(f"[signal_db] log_signal error: {e}")
        return -1


def mark_entered(signal_id: int, entry_price: float):
    """Mark a signal as entered (trade executed)."""
    try:
        conn = _get_conn()
        conn.execute("""
            UPDATE signals SET entered=1, entry_price=?, entry_time=? WHERE id=?
        """, (entry_price, datetime.now(timezone.utc).isoformat(), signal_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[signal_db] mark_entered error: {e}")


def log_outcome(signal_id: int, exit_price: float, pnl_pct: float, exit_reason: str):
    """Log the outcome of a signal (after position close). Updates ticker_stats."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        win = 1 if pnl_pct > 0 else 0
        c.execute("""
            INSERT INTO outcomes (signal_id, exit_price, exit_time, pnl_pct, exit_reason, win)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (signal_id, exit_price, datetime.now(timezone.utc).isoformat(), pnl_pct, exit_reason, win))

        # Get ticker for this signal
        row = c.execute("SELECT ticker, final_score FROM signals WHERE id=?", (signal_id,)).fetchone()
        if row:
            ticker = row["ticker"]
            score = row["final_score"] or 0.0
            _update_ticker_stats(c, ticker, pnl_pct, win, score)

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[signal_db] log_outcome error: {e}")


def _update_ticker_stats(c, ticker: str, pnl_pct: float, win: int, score: float):
    """Recompute ticker_stats from outcomes."""
    try:
        rows = c.execute("""
            SELECT o.pnl_pct, o.win, s.final_score
            FROM outcomes o JOIN signals s ON o.signal_id=s.id
            WHERE s.ticker=? AND o.pnl_pct IS NOT NULL
        """, (ticker,)).fetchall()
        if not rows:
            return
        wins = [r for r in rows if r["win"] == 1]
        losses = [r for r in rows if r["win"] == 0]
        avg_pnl = sum(r["pnl_pct"] for r in rows) / len(rows)
        win_rate = len(wins) / len(rows)
        avg_score_wins = sum(r["final_score"] or 0 for r in wins) / len(wins) if wins else 0
        avg_score_losses = sum(r["final_score"] or 0 for r in losses) / len(losses) if losses else 0
        total_signals = c.execute("SELECT COUNT(*) FROM signals WHERE ticker=?", (ticker,)).fetchone()[0]

        c.execute("""
            INSERT OR REPLACE INTO ticker_stats
            (ticker, total_signals, wins, losses, avg_pnl, win_rate, avg_score_wins, avg_score_losses, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, total_signals, len(wins), len(losses), avg_pnl, win_rate,
              avg_score_wins, avg_score_losses, datetime.now(timezone.utc).isoformat()))
    except Exception as e:
        print(f"[signal_db] _update_ticker_stats error: {e}")


def get_ticker_stats(ticker: str) -> dict:
    """Get win-rate stats for a ticker."""
    try:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM ticker_stats WHERE ticker=?", (ticker,)).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {}
    except Exception:
        return {}


def get_all_stats() -> list:
    """Get stats for all tickers."""
    try:
        conn = _get_conn()
        rows = conn.execute("SELECT * FROM ticker_stats ORDER BY win_rate DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_optimal_threshold(ticker: str, min_wr: float = 0.65) -> float:
    """Find the minimum score threshold that achieves min_wr for this ticker."""
    try:
        conn = _get_conn()
        rows = conn.execute("""
            SELECT s.final_score, o.win FROM signals s
            JOIN outcomes o ON o.signal_id=s.id
            WHERE s.ticker=? AND s.final_score IS NOT NULL
            ORDER BY s.final_score
        """, (ticker,)).fetchall()
        conn.close()
        if len(rows) < 5:
            return 7.0  # default
        for threshold in [6.0, 6.5, 7.0, 7.5, 8.0, 8.5]:
            above = [r for r in rows if r["final_score"] >= threshold]
            if len(above) >= 3:
                wr = sum(r["win"] for r in above) / len(above)
                if wr >= min_wr:
                    return threshold
        return 7.5
    except Exception:
        return 7.0


def get_recent_signals(limit: int = 10) -> list:
    """Get most recent signals with outcome info."""
    try:
        conn = _get_conn()
        rows = conn.execute("""
            SELECT s.*, o.pnl_pct, o.win, o.exit_reason
            FROM signals s LEFT JOIN outcomes o ON o.signal_id=s.id
            ORDER BY s.timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


if __name__ == "__main__":
    init_db()
    print(f"Signal DB initialized at {DB_PATH}")
    print("All stats:", get_all_stats())
