#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Post-Trade Reflection
Called by close_position.py after every trade closes.
Spawns a reflection agent (via OpenClaw sessions_spawn logic) that:
1. Reviews the trade decision vs. actual outcome
2. Extracts lessons learned
3. Stores the situation + lesson in BM25 persistent memory
4. Posts summary to #cooper-study

Usage:
  python3 scripts/reflect_on_trade.py \
    --ticker NVDA \
    --entry 185.50 \
    --exit 200.50 \
    --pnl-pct 8.1 \
    --direction long \
    --exit-reason take_profit \
    --score 7.4 \
    --conviction 7 \
    --market-context "VIX=21, F&G=45, BTC stable, oil+2%"
"""
import argparse
import subprocess
import sys
import json
import os
from pathlib import Path
from datetime import datetime
import pytz

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv
load_dotenv(REPO / ".env")

ET = pytz.timezone("America/New_York")


def post_discord(channel_id: str, msg: str):
    try:
        subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target", channel_id,
             "--message", msg],
            timeout=15, check=False
        )
    except Exception as e:
        print(f"Discord post failed: {e}")


def build_reflection_prompt(args) -> str:
    outcome = "WIN ✅" if args.pnl_pct > 0 else "LOSS ❌"
    return f"""You are the CooperCorp Reflection Engine. Review this completed trade and extract lessons.

## Trade Record
- Ticker: {args.ticker}
- Direction: {args.direction.upper()}
- Entry: ${args.entry:.2f} → Exit: ${args.exit:.2f}
- P&L: {args.pnl_pct:+.2f}% ({outcome})
- Exit reason: {args.exit_reason}
- Pre-trade score: {args.score} | Conviction: {args.conviction}
- Market context at entry: {args.market_context}
- Date: {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}

## Your Task
1. **Was this the right decision?** Given the score ({args.score}), conviction ({args.conviction}), and outcome ({args.pnl_pct:+.2f}%), was this a good trade to take?

2. **What drove the outcome?** What market factors (technical, macro, news, sentiment) most influenced the result? Which signals were reliable? Which were misleading?

3. **What should we do differently?**
   - If WIN: What can we do more of? Any sizing improvements?
   - If LOSS: What warning signs were present but ignored? Should the entry threshold have been higher?

4. **Situation summary** (1-2 sentences, used for BM25 memory retrieval):
   Write a dense summary of the market SITUATION at entry (not the outcome). Include: ticker sector, VIX level, trend direction, key catalyst, sentiment context.

5. **Lesson** (1 sentence, stored as the recommendation):
   The single most actionable lesson from this trade for future similar setups.

Output STRICTLY as JSON:
{{
  "correct_decision": true/false,
  "outcome_drivers": ["factor1", "factor2"],
  "improvement": "what to do differently",
  "situation_summary": "dense market situation description for BM25",
  "lesson": "single actionable lesson",
  "confidence_in_analysis": 1-5
}}"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--entry", type=float, required=True)
    parser.add_argument("--exit", type=float, required=True)
    parser.add_argument("--pnl-pct", type=float, required=True)
    parser.add_argument("--direction", default="long")
    parser.add_argument("--exit-reason", default="unknown")
    parser.add_argument("--score", type=float, default=0.0)
    parser.add_argument("--conviction", type=int, default=0)
    parser.add_argument("--market-context", default="")
    args = parser.parse_args()

    prompt = build_reflection_prompt(args)
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")

    print(f"[reflect_on_trade] Reflecting on {args.ticker} | P&L: {args.pnl_pct:+.2f}%")

    # Spawn reflection via openclaw sessions_spawn equivalent: use oracle or direct LLM call
    # We use openclaw CLI to run a quick isolated session
    result = subprocess.run(
        ["openclaw", "oracle", "--model", "sonnet", "--print", prompt],
        capture_output=True, text=True, timeout=90, cwd=str(REPO)
    )

    reflection_text = result.stdout.strip()

    # Parse JSON from output
    reflection = {}
    for line in reflection_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                # Find full JSON block
                start = reflection_text.find("{")
                end = reflection_text.rfind("}") + 1
                reflection = json.loads(reflection_text[start:end])
                break
            except Exception:
                pass

    if not reflection:
        # Fallback: store raw text as lesson
        reflection = {
            "situation_summary": f"{args.ticker} {args.direction} trade, VIX context: {args.market_context[:100]}",
            "lesson": reflection_text[:200] if reflection_text else "No reflection generated",
            "correct_decision": args.pnl_pct > 0,
            "confidence_in_analysis": 1,
        }

    # Store in BM25 persistent memory
    from tradingagents.memory import get_memory
    memory = get_memory()
    memory.add_situation(
        situation=reflection.get("situation_summary", f"{args.ticker} trade context"),
        recommendation=reflection.get("lesson", ""),
        ticker=args.ticker,
        pnl_pct=args.pnl_pct,
        outcome="win" if args.pnl_pct > 0 else "loss",
    )
    stats = memory.stats()

    # Post to #cooper-study
    outcome_emoji = "✅" if args.pnl_pct > 0 else "❌"
    correct = "✅ Right call" if reflection.get("correct_decision") else "⚠️ Questionable entry"
    msg_lines = [
        f"🧠 **Trade Reflection** | {now}",
        f"{outcome_emoji} **{args.ticker}** {args.direction.upper()} {args.pnl_pct:+.2f}% ({args.exit_reason})",
        f"Entry ${args.entry:.2f} → Exit ${args.exit:.2f} | Score {args.score} | Conviction {args.conviction}",
        "",
        f"**Decision:** {correct}",
        f"**Key drivers:** {', '.join(reflection.get('outcome_drivers', [])[:3])}",
        f"**Improvement:** {reflection.get('improvement', 'N/A')[:150]}",
        f"**💡 Lesson:** {reflection.get('lesson', 'N/A')[:150]}",
        "",
        f"Memory: {stats['total']} situations stored | {stats['wins']}W / {stats['losses']}L",
        "— Cooper 🦅 | Reflection Engine",
    ]
    post_discord("1468621074999541810", "\n".join(msg_lines))

    print(f"[reflect_on_trade] Done. Memory now has {stats['total']} situations.")
    print(json.dumps(reflection, indent=2))


if __name__ == "__main__":
    main()
