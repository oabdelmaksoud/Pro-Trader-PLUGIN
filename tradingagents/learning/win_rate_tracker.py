"""
CooperCorp PRJ-002 — Win-Rate Tracker
Reads from signal_db to track strategy performance and detect decay.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional


def get_ticker_win_rate(ticker: str, lookback_days: int = 90) -> dict:
    """Get win rate stats for a ticker over the lookback window."""
    try:
        from tradingagents.db.signal_db import _get_conn
        conn = _get_conn()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        rows = conn.execute("""
            SELECT o.pnl_pct, o.win FROM signals s
            JOIN outcomes o ON o.signal_id=s.id
            WHERE s.ticker=? AND s.timestamp >= ? AND o.pnl_pct IS NOT NULL
        """, (ticker, cutoff)).fetchall()
        conn.close()
        if not rows:
            return {"win_rate": None, "sample_size": 0, "avg_pnl": None}
        wins = sum(1 for r in rows if r["win"] == 1)
        avg_pnl = sum(r["pnl_pct"] for r in rows) / len(rows)
        return {"win_rate": wins / len(rows), "sample_size": len(rows), "avg_pnl": avg_pnl}
    except Exception:
        return {"win_rate": None, "sample_size": 0, "avg_pnl": None}


def detect_strategy_decay() -> tuple:
    """
    Returns (is_decaying: bool, message: str).
    True if last 10 completed signals have WR < 50%.
    """
    try:
        from tradingagents.db.signal_db import _get_conn
        conn = _get_conn()
        rows = conn.execute("""
            SELECT o.win FROM signals s
            JOIN outcomes o ON o.signal_id=s.id
            WHERE o.win IS NOT NULL
            ORDER BY s.timestamp DESC LIMIT 10
        """).fetchall()
        conn.close()
        if len(rows) < 10:
            return False, f"Insufficient data ({len(rows)} completed signals, need 10)"
        wr = sum(r["win"] for r in rows) / len(rows)
        if wr < 0.50:
            return True, f"⚠️ Strategy decay detected: last 10 signals WR={wr:.1%} (below 50%)"
        return False, f"Strategy healthy: last 10 signals WR={wr:.1%}"
    except Exception as e:
        return False, f"Error: {e}"


def get_best_tickers(min_signals: int = 5, min_wr: float = 0.6) -> list:
    """Return tickers with sufficient history and good win rates."""
    try:
        from tradingagents.db.signal_db import get_all_stats
        stats = get_all_stats()
        return [
            s["ticker"] for s in stats
            if s.get("total_signals", 0) >= min_signals and s.get("win_rate", 0) >= min_wr
        ]
    except Exception:
        return []


def get_global_stats() -> dict:
    """Get overall system win rate across all tickers."""
    try:
        from tradingagents.db.signal_db import _get_conn
        conn = _get_conn()
        rows = conn.execute("""
            SELECT o.pnl_pct, o.win FROM outcomes o WHERE o.win IS NOT NULL
        """).fetchall()
        conn.close()
        if not rows:
            return {"total_trades": 0, "win_rate": None, "avg_pnl": None}
        wins = sum(1 for r in rows if r["win"] == 1)
        avg_pnl = sum(r["pnl_pct"] for r in rows) / len(rows)
        return {
            "total_trades": len(rows),
            "win_rate": wins / len(rows),
            "avg_pnl": avg_pnl,
            "is_decaying": wins / len(rows) < 0.5 if len(rows) >= 10 else None
        }
    except Exception:
        return {}
