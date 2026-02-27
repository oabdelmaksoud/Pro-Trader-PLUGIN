#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Unified Analysis Entry Point
Runs the full TradingAgents LangGraph pipeline for a ticker.
Used by crons AND by run_live.py.

Usage:
  python3 scripts/analyze.py --ticker NVDA
  python3 scripts/analyze.py --ticker NVDA --output json
"""
import argparse, json, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import os

# Check if Anthropic key is available before importing LangGraph
_anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
_use_langgraph = bool(_anthropic_key)

if _use_langgraph:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
else:
    import warnings
    warnings.warn(
        "ANTHROPIC_API_KEY not set. analyze.py requires the key for LangGraph pipeline. "
        "For cron-based trading, use sessions_spawn via cron agentTurn (no key needed). "
        "Set ANTHROPIC_API_KEY in .env to use this script directly.",
        stacklevel=2
    )

_alpha_key = os.getenv("ALPHA_VANTAGE_KEY", "")

COOPER_CONFIG = {
    "llm_provider": "anthropic",
    "deep_think_llm": "claude-opus-4-6",      # Trader + Bull + Bear use this
    "quick_think_llm": "claude-sonnet-4-6",    # Analysts use this
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,
    "online_tools": True,
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "alpha_vantage" if _alpha_key else "yfinance",
    },
}


def run_analysis(ticker: str, trade_date: str = None) -> dict:
    """Run full pipeline and return structured result."""
    if not _use_langgraph:
        return {
            "ticker": ticker,
            "date": trade_date or str(date.today()),
            "action": "HOLD",
            "score": 0.0,
            "conviction": 0,
            "decision_text": "ERROR: ANTHROPIC_API_KEY not set. This script requires LangGraph. Use cron agentTurn (sessions_spawn) for key-free analysis.",
            "state": {},
            "error": "ANTHROPIC_API_KEY not set",
        }
    trade_date = trade_date or str(date.today())
    merged = {**DEFAULT_CONFIG, **COOPER_CONFIG}
    graph = TradingAgentsGraph(config=merged)
    state, decision = graph.propagate(ticker, trade_date)

    # Extract score and conviction from decision text
    import re
    score_match = re.search(r'[Ss]core[:\s]+(\d+\.?\d*)', decision)
    conviction_match = re.search(r'[Cc]onviction[:\s]+(\d+)', decision)
    action_match = re.search(r'\b(BUY|SELL|HOLD)\b', decision.upper())

    return {
        "ticker": ticker,
        "date": trade_date,
        "action": action_match.group(1) if action_match else "HOLD",
        "score": float(score_match.group(1)) if score_match else 0.0,
        "conviction": int(conviction_match.group(1)) if conviction_match else 0,
        "decision_text": decision,
        "state": {
            "market_report": state.get("market_report", ""),
            "news_report": state.get("news_report", ""),
            "sentiment_report": state.get("sentiment_report", ""),
            "fundamentals_report": state.get("fundamentals_report", ""),
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--date", default=str(date.today()))
    parser.add_argument("--output", choices=["text", "json"], default="text")
    args = parser.parse_args()

    result = run_analysis(args.ticker, args.date)

    if args.output == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"🦅 {result['ticker']} Analysis — {result['date']}")
        print(f"{'='*60}")
        print(f"Action: {result['action']} | Score: {result['score']}/10 | Conviction: {result['conviction']}/10")
        print(f"\nDecision:\n{result['decision_text'][:800]}")


if __name__ == "__main__":
    main()
