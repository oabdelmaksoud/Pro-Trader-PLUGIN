#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Live Trading Pipeline
Usage:
  python scripts/run_live.py --ticker AAPL            # dry run (analysis only)
  python scripts/run_live.py --ticker AAPL --execute  # place real paper order
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.execution import TradeExecutor

COOPER_CONFIG = {
    "llm_provider": "anthropic",
    "deep_think_llm": "claude-opus-4-6",
    "quick_think_llm": "claude-sonnet-4-6",
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,
    "data_vendor": "yfinance",
    "online_tools": True,
}

def main():
    parser = argparse.ArgumentParser(description="CooperCorp Trading Pipeline")
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol")
    parser.add_argument("--date", default=str(date.today()), help="Trade date (YYYY-MM-DD)")
    parser.add_argument("--execute", action="store_true", help="Place real order (default: dry run)")
    parser.add_argument("--pct", type=float, default=0.05, help="Portfolio pct per trade (default 5%%)")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    trade_date = args.date
    dry_run = not args.execute

    print(f"\n🦅 CooperCorp Trading Pipeline")
    print(f"   Ticker: {ticker} | Date: {trade_date} | {'DRY RUN' if dry_run else '🔴 LIVE EXECUTION'}")
    print("=" * 60)

    # Run TradingAgents graph
    print("\n⏳ Running multi-agent analysis...")
    graph = TradingAgentsGraph(config=COOPER_CONFIG)
    state, decision = graph.propagate(ticker, trade_date)

    print(f"\n📊 Final Decision:\n{decision}\n")

    # Parse & execute
    executor = TradeExecutor(portfolio_pct=args.pct)
    parsed = executor.parse_decision(decision, ticker)
    print(f"✅ Parsed action: {parsed['action']}")

    order = executor.execute(parsed, dry_run=dry_run)

    if order:
        if dry_run:
            print(f"🔍 DRY RUN — would {order['side'].upper()} {order['qty']} shares of {ticker}")
        else:
            print(f"🚀 ORDER PLACED: {order}")
    else:
        print(f"⏸️  HOLD — no order placed")

    # Save run log
    log_dir = Path(__file__).parent.parent / "logs" / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{ticker}_{trade_date}.json"
    with open(log_file, "w") as f:
        json.dump({
            "ticker": ticker,
            "date": trade_date,
            "decision": decision,
            "parsed": parsed,
            "order": order,
            "dry_run": dry_run,
        }, f, indent=2)
    print(f"\n💾 Run saved to {log_file}")

if __name__ == "__main__":
    main()
