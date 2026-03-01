"""
position_calibrator.py — Rolling position size calibrator
Called after each trade close.
Uses Kelly Criterion (half-Kelly) based on last 30 completed trades from signal_db.sqlite.
Writes to logs/kelly_params.json.
"""

import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

LOGS_DIR = REPO / "logs"
LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = LOGS_DIR / "kelly_params.json"
DB_PATH = REPO / "signal_db.sqlite"

DEFAULT_FRACTION = 0.01  # 1% when insufficient data
MAX_FRACTION = 0.02       # Hard cap at 2%
MIN_SAMPLE_SIZE = 10


def load_trades(db_path: Path) -> list:
    """Load last 30 completed trades from signal_db.sqlite."""
    if not db_path.exists():
        print(f"[position_calibrator] DB not found: {db_path}")
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Try common schema patterns — gracefully fallback
        try:
            cur.execute("""
                SELECT pnl_pct, entry_price, exit_price
                FROM trades
                WHERE status = 'closed'
                ORDER BY closed_at DESC
                LIMIT 30
            """)
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            try:
                cur.execute("""
                    SELECT pnl_pct
                    FROM signals
                    WHERE status = 'closed'
                    ORDER BY id DESC
                    LIMIT 30
                """)
                rows = cur.fetchall()
            except sqlite3.OperationalError as e:
                print(f"[position_calibrator] Schema error: {e}")
                rows = []
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[position_calibrator] DB error: {e}")
        return []


def calculate_kelly(trades: list) -> dict:
    """Calculate Kelly fraction from trade list."""
    if not trades or len(trades) < MIN_SAMPLE_SIZE:
        return {
            "kelly_fraction": DEFAULT_FRACTION,
            "half_kelly": DEFAULT_FRACTION,
            "win_rate": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "profit_factor": None,
            "sample_size": len(trades),
            "note": f"Insufficient data (<{MIN_SAMPLE_SIZE} trades). Using default {DEFAULT_FRACTION}."
        }

    try:
        pnl_pcts = []
        for t in trades:
            pnl = t.get("pnl_pct")
            if pnl is None:
                # Calculate from entry/exit if available
                entry = t.get("entry_price")
                exit_ = t.get("exit_price")
                if entry and exit_ and entry != 0:
                    pnl = (exit_ - entry) / entry * 100
            if pnl is not None:
                pnl_pcts.append(float(pnl))

        if not pnl_pcts:
            raise ValueError("No valid PnL data")

        wins = [p for p in pnl_pcts if p > 0]
        losses = [p for p in pnl_pcts if p <= 0]

        win_rate = len(wins) / len(pnl_pcts)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Kelly formula
        if avg_loss > 0 and avg_win > 0:
            kelly = win_rate - (1 - win_rate) / (avg_win / avg_loss)
        elif avg_win > 0:
            kelly = win_rate
        else:
            kelly = 0.0

        kelly = max(0.0, kelly)  # Don't go negative
        half_kelly = min(kelly / 2, MAX_FRACTION)
        half_kelly = max(half_kelly, DEFAULT_FRACTION * 0.5)  # Floor at 0.5%

        return {
            "kelly_fraction": round(kelly, 4),
            "half_kelly": round(half_kelly, 4),
            "win_rate": round(win_rate, 4),
            "avg_win_pct": round(avg_win, 4),
            "avg_loss_pct": round(avg_loss, 4),
            "profit_factor": round(profit_factor, 4),
            "sample_size": len(pnl_pcts),
        }
    except Exception as e:
        print(f"[position_calibrator] Kelly calculation error: {e}")
        return {
            "kelly_fraction": DEFAULT_FRACTION,
            "half_kelly": DEFAULT_FRACTION,
            "sample_size": len(trades),
            "error": str(e)
        }


def main():
    trades = load_trades(DB_PATH)
    params = calculate_kelly(trades)
    params["updated"] = datetime.utcnow().isoformat()
    params["max_position_size"] = MAX_FRACTION

    # Write output
    try:
        OUTPUT_FILE.write_text(json.dumps(params, indent=2))
        print(f"[position_calibrator] Wrote to {OUTPUT_FILE}")
    except Exception as e:
        print(f"[position_calibrator] Failed to write output: {e}")

    # Print summary
    print("\n=== POSITION CALIBRATOR SUMMARY ===")
    print(f"Sample size:    {params.get('sample_size', 0)} trades")
    print(f"Win rate:       {params.get('win_rate', 'N/A')}")
    print(f"Profit factor:  {params.get('profit_factor', 'N/A')}")
    print(f"Kelly fraction: {params.get('kelly_fraction', 'N/A')}")
    print(f"Half-Kelly:     {params.get('half_kelly', DEFAULT_FRACTION)} (use this for sizing)")
    if "note" in params:
        print(f"Note:           {params['note']}")
    print("===================================\n")

    return params


if __name__ == "__main__":
    main()
