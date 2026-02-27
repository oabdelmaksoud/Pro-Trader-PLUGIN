#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Live Trading Pipeline
Usage:
  python scripts/run_live.py --ticker AAPL              # dry run + post to Discord
  python scripts/run_live.py --ticker AAPL --execute    # execute paper trade
  python scripts/run_live.py --ticker AAPL --no-discord # skip Discord posting
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.execution import TradeExecutor
from tradingagents.discord_reporter import post_analysis, post_trade

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
    parser.add_argument("--execute", action="store_true", help="Place real paper order")
    parser.add_argument("--pct", type=float, default=0.05, help="Portfolio %% per trade (default 5%%)")
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord posting")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    trade_date = args.date
    dry_run = not args.execute
    post_discord = not args.no_discord

    print(f"\n🦅 CooperCorp Trading Pipeline")
    print(f"   Ticker: {ticker} | Date: {trade_date} | {'DRY RUN' if dry_run else '🔴 LIVE PAPER'}")
    print("=" * 60)

    # Run full multi-agent analysis
    print("\n⏳ Running multi-agent analysis (may take a few minutes)…")
    graph = TradingAgentsGraph(config=COOPER_CONFIG)
    state, decision = graph.propagate(ticker, trade_date)
    print(f"\n✅ Analysis complete")
    print(f"\n📋 Final Decision:\n{decision[:800]}")

    # Parse & execute
    executor = TradeExecutor(portfolio_pct=args.pct)
    parsed = executor.parse_decision(decision, ticker)
    action = parsed["action"]
    print(f"\n🎯 Parsed: {action}")

    order = executor.execute(parsed, dry_run=dry_run)
    if order:
        print(f"📦 Order: {order}")
    else:
        print("⏸️  HOLD — no order placed")

    # Post to Discord
    if post_discord:
        print("\n📨 Posting to Discord…")
        reports = {
            "market_report":       state.get("market_report", ""),
            "news_report":         state.get("news_report", ""),
            "sentiment_report":    state.get("sentiment_report", ""),
            "fundamentals_report": state.get("fundamentals_report", ""),
        }
        post_analysis(ticker, trade_date, reports, decision, action)
        post_trade(ticker, trade_date, action, order, dry_run, decision)
        print("✅ Posted to #war-room-hive-mind and #paper-trades")

    # Save run log
    log_dir = Path(__file__).parent.parent / "logs" / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{ticker}_{trade_date}.json"
    with open(log_file, "w") as f:
        json.dump({
            "ticker": ticker, "date": trade_date,
            "decision": decision, "parsed": parsed,
            "order": order, "dry_run": dry_run,
        }, f, indent=2)
    print(f"\n💾 Saved to {log_file}")

if __name__ == "__main__":
    main()
