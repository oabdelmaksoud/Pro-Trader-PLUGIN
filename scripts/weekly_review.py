#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Weekly Performance Review
Runs every Monday 7:30 AM ET.
Synthesizes the past week's trades, lessons, and patterns into a review
and posts to Discord #cooper-study and #paper-trades.
"""
import json
import os
import sys
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

LEDGER_PATH = REPO_ROOT / "logs" / "ledger.jsonl"
LESSONS_PATH = REPO_ROOT / "logs" / "LESSONS.md"
PATTERNS_PATH = REPO_ROOT / "logs" / "patterns.json"
ADJUSTMENTS_PATH = REPO_ROOT / "logs" / "score_adjustments.json"

DISCORD_STUDY_CHANNEL = "1468621074999541810"
DISCORD_PAPER_TRADES_CHANNEL = "1468597633756037385"


def load_week_trades() -> list:
    """Load trades from the past 7 days."""
    if not LEDGER_PATH.exists():
        return []
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    trades = []
    with open(LEDGER_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
                if t.get("date", "") >= cutoff:
                    trades.append(t)
            except Exception:
                pass
    return trades


def load_patterns() -> dict:
    if not PATTERNS_PATH.exists():
        return {}
    try:
        with open(PATTERNS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def load_adjustments() -> dict:
    if not ADJUSTMENTS_PATH.exists():
        return {}
    try:
        with open(ADJUSTMENTS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def compute_stats(trades: list) -> dict:
    if not trades:
        return {}
    wins = [t for t in trades if t.get("pnl_dollar", 0) > 0]
    losses = [t for t in trades if t.get("pnl_dollar", 0) <= 0]
    total_pnl = sum(t.get("pnl_dollar", 0) for t in trades)

    sorted_pnl = sorted(trades, key=lambda t: t.get("pnl_dollar", 0))
    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "best": sorted_pnl[-1] if sorted_pnl else None,
        "worst": sorted_pnl[0] if sorted_pnl else None,
        "avg_win_pct": sum(t.get("pnl_pct", 0) for t in wins) / len(wins) if wins else 0,
        "avg_loss_pct": sum(t.get("pnl_pct", 0) for t in losses) / len(losses) if losses else 0,
    }


def build_report(stats: dict, patterns: dict, adjustments: dict) -> str:
    week_ending = date.today().isoformat()
    week_start = (date.today() - timedelta(days=7)).isoformat()

    if not stats:
        return f"📊 **Weekly Review | {week_start} → {week_ending}**\n\nNo trades recorded this week."

    best = stats.get("best", {})
    worst = stats.get("worst", {})
    best_str = f"{best.get('ticker','?')} {best.get('pnl_pct',0):+.1%} (${best.get('pnl_dollar',0):+.2f})" if best else "N/A"
    worst_str = f"{worst.get('ticker','?')} {worst.get('pnl_pct',0):+.1%} (${worst.get('pnl_dollar',0):+.2f})" if worst else "N/A"

    # Top 3 recurring mistakes
    top_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:3]
    mistakes_lines = "\n".join(
        f"  {i+1}. `{pat}` — {cnt}x"
        for i, (pat, cnt) in enumerate(top_patterns)
    ) or "  None recorded."

    # Active adjustments
    adj_lines = []
    for pat, data in adjustments.items():
        desc = data.get("rule", {}).get("description", "")
        adj_lines.append(f"  • `{pat}`: {desc}")
    adj_str = "\n".join(adj_lines) or "  None active."

    report = (
        f"📊 **CooperCorp Weekly Review | {week_start} → {week_ending}**\n\n"
        f"**Performance**\n"
        f"  Trades: {stats['total']} | Wins: {stats['wins']} | Losses: {stats['losses']}\n"
        f"  Win Rate: {stats['win_rate']:.1%} | Total P&L: ${stats['total_pnl']:+.2f}\n"
        f"  Avg Win: {stats['avg_win_pct']:+.1%} | Avg Loss: {stats['avg_loss_pct']:+.1%}\n"
        f"  Best: {best_str}\n"
        f"  Worst: {worst_str}\n\n"
        f"**Top Recurring Mistakes This Week**\n{mistakes_lines}\n\n"
        f"**Active Score Adjustments (now applied to every scan)**\n{adj_str}\n\n"
        f"**Strategy Evolution Notes**\n"
        f"  Pattern count drives automatic scoring adjustments. "
        f"Patterns with 2+ occurrences trigger score changes; "
        f"3+ occurrences trigger hard rules (blocks, caps, vetos).\n\n"
        f"_Review generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
    )
    return report


def post_to_discord(channel_id: str, message: str):
    """Post a message to a Discord channel via OpenClaw."""
    try:
        result = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target", channel_id,
             "--message", message],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"Discord post failed: {result.stderr}", file=sys.stderr)
        else:
            print(f"Posted to {channel_id}")
    except Exception as e:
        print(f"Discord post error: {e}", file=sys.stderr)


def update_lessons_md(report: str):
    """Append weekly synthesis to LESSONS.md."""
    if not LESSONS_PATH.exists():
        LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        LESSONS_PATH.write_text(
            "# CooperCorp Trading — Lessons Learned\n\n"
            "## Individual Trade Post-Mortems\n\n"
        )
    week = date.today().isoformat()
    section = f"\n## Weekly Synthesis — {week}\n\n{report}\n\n---\n"
    with open(LESSONS_PATH, "a") as f:
        f.write(section)
    print("LESSONS.md updated")


def main():
    print(f"Weekly review starting: {datetime.now(timezone.utc).isoformat()}")

    trades = load_week_trades()
    stats = compute_stats(trades)
    patterns = load_patterns()
    adjustments = load_adjustments()

    report = build_report(stats, patterns, adjustments)
    print(report)

    # Post to both Discord channels
    post_to_discord(DISCORD_STUDY_CHANNEL, report)
    post_to_discord(DISCORD_PAPER_TRADES_CHANNEL, report)

    # Update LESSONS.md
    update_lessons_md(report)

    print("Weekly review complete.")


if __name__ == "__main__":
    main()
