#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — News-to-Trade Trigger
When breaking news fires during market hours, this script:
1. Gathers full data for affected tickers
2. Scores each ticker (including the breaking news signal)
3. Runs trade_gate.py if score meets threshold
4. Posts result to Discord

Usage:
  python3 scripts/news_trade_trigger.py \
    --tickers XOM,CVX,LMT \
    --tier TIER1 \
    --headline "Iran closes Strait of Hormuz" \
    --category GEOPOLITICAL \
    --direction long   # long|short|neutral
"""
import argparse
import subprocess
import sys
import json
import os
from pathlib import Path
from datetime import datetime, time as dtime
import pytz

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv
load_dotenv(REPO / ".env")

ET = pytz.timezone("America/New_York")

# Score boost injected for news-triggered scans (on top of normal score)
TIER_BOOST = {"TIER1": 1.5, "TIER2": 0.7}

# Market hours for news-triggered trades (more conservative than normal scans)
NEWS_ENTRY_OPEN  = dtime(9, 35)   # 5min after open (avoid chaos)
NEWS_ENTRY_CLOSE = dtime(14, 15)  # earlier cutoff for news trades


def is_market_hours() -> bool:
    now = datetime.now(ET).time()
    return NEWS_ENTRY_OPEN <= now <= NEWS_ENTRY_CLOSE


def post_discord(channel_id: str, msg: str):
    """Post to Discord via openclaw CLI."""
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


def gather_data(ticker: str) -> dict:
    """Run get_market_data.py --full for ticker."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "get_market_data.py"),
         "--ticker", ticker, "--full", "--json"],
        capture_output=True, text=True, timeout=60, cwd=str(REPO)
    )
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except Exception:
            pass
    return {}


def score_ticker(ticker: str, data: dict, tier: str, direction: str) -> float:
    """Pull pre-score from data and apply news boost."""
    base_score = float(data.get("score", 5.0))
    boost = TIER_BOOST.get(tier, 0.5)
    # Direction alignment bonus
    if direction == "long" and data.get("trend", "") in ("bullish", "neutral"):
        boost += 0.3
    elif direction == "short" and data.get("trend", "") in ("bearish", "neutral"):
        boost += 0.3
    return min(10.0, base_score + boost)


def run_trade_gate(ticker: str, score: float, direction: str,
                   headline: str, tier: str) -> dict:
    """Call trade_gate.py with news-boosted score."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "trade_gate.py"),
         "--ticker", ticker,
         "--score", str(round(score, 2)),
         "--direction", direction,
         "--source", f"breaking_news_{tier.lower()}",
         "--note", headline[:120]],
        capture_output=True, text=True, timeout=90, cwd=str(REPO)
    )
    out = result.stdout + result.stderr
    try:
        # trade_gate.py prints a JSON result line
        for line in reversed(out.splitlines()):
            if line.strip().startswith("{"):
                return json.loads(line.strip())
    except Exception:
        pass
    return {"status": "unknown", "output": out[-500:]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True,
                        help="Comma-separated tickers, e.g. XOM,CVX,LMT")
    parser.add_argument("--tier", default="TIER1",
                        choices=["TIER1", "TIER2"])
    parser.add_argument("--headline", required=True,
                        help="Breaking news headline")
    parser.add_argument("--category", default="BREAKING",
                        help="Category: GEOPOLITICAL, MACRO, SECTOR, etc.")
    parser.add_argument("--direction", default="long",
                        choices=["long", "short", "neutral"])
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    now_et = datetime.now(ET).strftime("%I:%M %p ET")

    # Gate: market hours only
    if not is_market_hours():
        print(f"[news_trade_trigger] Outside news-entry window ({now_et}). "
              f"Queued tickers for next scan: {tickers}")
        # Post note to war-room so human knows
        post_discord("1469763123010342953",
            f"📋 **News-Trade Queued** | {now_et}\n"
            f"Tickers: {', '.join(tickers)} | Outside entry window\n"
            f"Headline: {args.headline[:100]}\n"
            f"Will be picked up at next market scan."
        )
        return

    print(f"[news_trade_trigger] Market hours ✅ | Processing {tickers} | {now_et}")

    results = []
    for ticker in tickers[:3]:  # max 3 tickers per news event
        print(f"\n--- {ticker} ---")

        # 1. Gather data
        print(f"  Gathering data...")
        data = gather_data(ticker)
        if not data:
            print(f"  No data for {ticker}, skipping")
            continue

        # 2. Score with news boost
        score = score_ticker(ticker, data, args.tier, args.direction)
        print(f"  Base score: {data.get('score', '?')} → News-boosted: {score:.2f}")

        # 3. Check threshold (news trades need score ≥ 7.0)
        if score < 7.0:
            print(f"  Score {score:.2f} < 7.0 threshold — no trade")
            results.append({"ticker": ticker, "score": score, "action": "skip_threshold"})
            continue

        # 4. Run trade gate
        print(f"  Running trade gate (score={score:.2f}, direction={args.direction})...")
        gate_result = run_trade_gate(ticker, score, args.direction,
                                     args.headline, args.tier)
        print(f"  Gate result: {gate_result.get('status', 'unknown')}")

        results.append({
            "ticker": ticker,
            "score": score,
            "action": gate_result.get("status", "unknown"),
            "gate": gate_result,
        })

    # 5. Post summary to #war-room
    emoji_map = {"TIER1": "🚨", "TIER2": "⚡"}
    emoji = emoji_map.get(args.tier, "⚡")

    lines = [
        f"{emoji} **News-Trade Trigger** | {now_et}",
        f"📰 {args.headline[:120]}",
        f"📂 Category: {args.category} | Direction: {args.direction.upper()}",
        "",
    ]
    for r in results:
        status = r.get("action", "?")
        icon = "✅" if "filled" in status or "submitted" in status else \
               "⏭️" if "skip" in status or "gate" in status else "❓"
        lines.append(f"{icon} **{r['ticker']}** — score {r.get('score', '?'):.1f} → {status}")

    if not results:
        lines.append("⚠️ No tradeable tickers after scoring.")

    lines.append("\n— Cooper 🦅 | News-to-Trade")
    summary = "\n".join(lines)

    post_discord("1469763123010342953", summary)
    print(f"\n[news_trade_trigger] Done. Posted to #war-room.")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
