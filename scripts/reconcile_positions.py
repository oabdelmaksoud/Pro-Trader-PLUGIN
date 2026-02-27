#!/usr/bin/env python3
"""
Detects positions at Alpaca that don't have open_trades/ records.
Flags them so the system can manage them properly.
Run at startup and after any system restart.
"""
import sys, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from tradingagents.brokers.alpaca import AlpacaBroker

OPEN_TRADES_DIR = Path(__file__).parent.parent / "logs" / "open_trades"
ORPHAN_LOG = Path(__file__).parent.parent / "logs" / "orphaned_positions.json"


def main():
    broker = AlpacaBroker()
    positions = broker.get_positions()

    orphans = []
    for pos in positions:
        trade_file = OPEN_TRADES_DIR / f"{pos.symbol}.json"
        if not trade_file.exists():
            orphan = {
                "symbol": pos.symbol,
                "qty": float(pos.qty),
                "entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "pnl_pct": float(pos.unrealized_plpc) * 100,
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "action": "MONITORING_ONLY",  # Don't close blindly
            }
            orphans.append(orphan)

            # Create a synthetic open_trades record so the system can manage it
            OPEN_TRADES_DIR.mkdir(parents=True, exist_ok=True)
            trade_file.write_text(json.dumps({
                "symbol": pos.symbol,
                "side": "long" if float(pos.qty) > 0 else "short",
                "entry_price": float(pos.avg_entry_price),
                "qty": abs(float(pos.qty)),
                "analysis_at_entry": "ORPHANED_POSITION — existed before system setup or recovery",
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "date": datetime.now(timezone.utc).date().isoformat(),
                "is_orphan": True,
            }, indent=2))
            print(f"ORPHAN: {pos.symbol} qty={pos.qty} entry=${float(pos.avg_entry_price):.2f} P&L={float(pos.unrealized_plpc)*100:.1f}%")

    if orphans:
        ORPHAN_LOG.write_text(json.dumps(orphans, indent=2))
        print(f"\n{len(orphans)} orphaned positions detected and registered.")
        print("They will now be monitored by the 15-min position monitor.")

        # Alert Discord
        import subprocess
        msg = f"⚠️ ORPHAN POSITIONS DETECTED: {', '.join(o['symbol'] for o in orphans)}\nRegistered for monitoring. Review open_trades/ records."
        subprocess.run(["openclaw", "message", "send", "--channel", "discord", "--target", "1468597633756037385", "--message", msg])
    else:
        print("No orphaned positions. All positions have open_trades records.")


if __name__ == "__main__":
    main()
