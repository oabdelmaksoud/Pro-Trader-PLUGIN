#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Performance CLI
Prints trade P&L metrics from the ledger.

Usage:
  python3 scripts/performance.py           # last 30 days
  python3 scripts/performance.py --days 7
  python3 scripts/performance.py --all
  python3 scripts/performance.py --today
"""
import argparse
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tradingagents.performance.ledger import TradeLedger


def main():
    parser = argparse.ArgumentParser(description="CooperCorp Trade Performance")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--days", type=int, default=30, help="Show last N days (default: 30)")
    group.add_argument("--all", action="store_true", help="Show all-time stats")
    group.add_argument("--today", action="store_true", help="Show today's stats only")
    args = parser.parse_args()

    ledger = TradeLedger()

    if args.today:
        s = ledger.daily_summary()
        print(f"\n📅 Today ({s['date']})")
        print(f"  Trades:    {s['trades']}")
        print(f"  Wins/Loss: {s['wins']}/{s['losses']}")
        print(f"  Total P&L: ${s['total_pnl']:+,.2f}")
        return

    days = None if args.all else args.days
    s = ledger.summary(days=days)
    period = "All-Time" if args.all else f"Last {args.days} Days"

    print(f"\n📊 CooperCorp Performance — {period}")
    print("=" * 45)
    print(f"  Total Trades:   {s['total_trades']}")
    print(f"  Wins / Losses:  {s['wins']} / {s['losses']}")
    print(f"  Win Rate:       {s['win_rate']:.1%}")
    print(f"  Avg Win:        {s['avg_win_pct']:+.2%}")
    print(f"  Avg Loss:       {s['avg_loss_pct']:+.2%}")
    print(f"  Profit Factor:  {s['profit_factor']}")
    print(f"  Total P&L:      ${s['total_pnl']:+,.2f}")

    if s['best_trade']:
        b = s['best_trade']
        print(f"\n  🏆 Best Trade:  {b['ticker']} {b['side']} ${b['pnl_dollar']:+.2f} ({b['pnl_pct']:+.2%})")
    if s['worst_trade']:
        w = s['worst_trade']
        print(f"  💀 Worst Trade: {w['ticker']} {w['side']} ${w['pnl_dollar']:+.2f} ({w['pnl_pct']:+.2%})")
    print()


if __name__ == "__main__":
    main()
