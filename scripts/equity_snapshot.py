#!/usr/bin/env python3
"""Daily equity snapshot. Run at 4:05 PM after market close."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
from tradingagents.brokers.alpaca import AlpacaBroker

EQUITY_FILE = Path(__file__).parent.parent / "logs" / "equity_curve.jsonl"


def main():
    broker = AlpacaBroker()
    account = broker.api.get_account()
    snapshot = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "equity": float(account.equity),
        "buying_power": float(account.buying_power),
        "unrealized_pl": float(account.unrealized_pl),
        "realized_pl_today": float(account.realized_pl),
        "positions": len(broker.get_positions()),
    }
    EQUITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EQUITY_FILE, "a") as f:
        f.write(json.dumps(snapshot) + "\n")
    print(f"Equity snapshot: ${snapshot['equity']:,.2f} | P&L today: ${snapshot['realized_pl_today']:+,.2f}")


if __name__ == "__main__":
    main()
