#!/usr/bin/env python3
"""CooperCorp PRJ-002 — Alpaca Account Status"""
import os, subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from tradingagents.brokers.alpaca import AlpacaBroker

ACCOUNT_FLOOR = 90_000.0  # Alert if portfolio drops below this


def check_floor_alert(broker):
    value = broker.get_portfolio_value()
    if value < ACCOUNT_FLOOR:
        msg = f"⚠️ ACCOUNT ALERT: Portfolio at ${value:,.2f} — below floor ${ACCOUNT_FLOOR:,.2f}. Review immediately."
        subprocess.run([
            "openclaw", "message", "send",
            "--channel", "discord",
            "--target", "1468597633756037385",
            "--message", msg
        ])
        print(f"ALERT SENT: {msg}")
    else:
        print(f"Account OK: ${value:,.2f} (floor: ${ACCOUNT_FLOOR:,.2f})")


broker = AlpacaBroker()
s = broker.status_summary()

print("\n🦅 CooperCorp — Alpaca Paper Account")
print("=" * 40)
print(f"  Status:          {s['status']}")
print(f"  Portfolio value: ${s['portfolio_value']:>12,.2f}")
print(f"  Buying power:    ${s['buying_power']:>12,.2f}")
print(f"  Cash:            ${s['cash']:>12,.2f}")
print(f"  Open positions:  {s['positions']}")
print()

positions = broker.get_positions()
if positions:
    print("📊 Positions:")
    for p in positions:
        print(f"  {p.symbol:<6} qty={p.qty:<6} avg=${float(p.avg_entry_price):.2f}  P&L=${float(p.unrealized_pl):.2f}")
else:
    print("📊 No open positions")

orders = broker.list_orders("open")
if orders:
    print(f"\n📋 Open Orders: {len(orders)}")
    for o in orders:
        print(f"  {o.side.upper()} {o.qty} {o.symbol} @ {o.type}")
else:
    print("\n📋 No open orders")
print()

# Floor alert check
check_floor_alert(broker)
