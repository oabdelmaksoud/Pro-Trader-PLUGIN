"""
CooperCorp PRJ-002 — Discord Reporter
Posts trade signals and execution results to the trading Discord server
via the OpenClaw CLI (no direct bot token needed).
"""
import json
import subprocess
from datetime import datetime, timezone
from typing import Optional

# Channel IDs — CooperCorp Trading Server (1467898695436730420)
CHANNELS = {
    "paper_trades":   "1468597633756037385",  # Cooper's autonomous paper trade logs
    "war_room":       "1469763123010342953",  # Bull/Bear debate output
    "winning_trades": "1468620383019077744",  # Hall of Fame
    "losing_trades":  "1468620412849229825",  # Hall of Shame
    "cooper_study":   "1468621074999541810",  # Strategy Lab / research
    "private":        "1469519503174926568",  # gamespoofer private
}

DECISION_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⏸️"}


def _send(channel_id: str, message: str) -> bool:
    """Post a message to a Discord channel via OpenClaw CLI."""
    try:
        result = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target", channel_id,
             "--message", message],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            print(f"[discord] Send failed: {result.stderr[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[discord] Error: {e}")
        return False


def post_analysis(ticker: str, trade_date: str, reports: dict, decision_text: str, action: str) -> bool:
    """Post full analysis to #war-room-hive-mind (debate channel)."""
    emoji = DECISION_EMOJI.get(action, "❓")
    truncate = lambda s, n=600: (s[:n] + "…") if len(s) > n else s
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = (
        f"## {emoji} {ticker} Multi-Agent Analysis — {trade_date}\n"
        f"**📊 Market:** {truncate(reports.get('market_report','N/A'))}\n\n"
        f"**📰 News:** {truncate(reports.get('news_report','N/A'))}\n\n"
        f"**💬 Sentiment:** {truncate(reports.get('sentiment_report','N/A'))}\n\n"
        f"**📈 Fundamentals:** {truncate(reports.get('fundamentals_report','N/A'))}\n\n"
        f"**🧠 Agent Decision:** {truncate(decision_text, 800)}\n\n"
        f"*CooperCorp PRJ-002 | {ts}*"
    )
    return _send(CHANNELS["war_room"], msg)


def post_trade(ticker: str, trade_date: str, action: str, order: Optional[dict], dry_run: bool, decision_text: str) -> bool:
    """Post trade execution card to #paper-trades."""
    emoji = DECISION_EMOJI.get(action, "❓")
    mode = "DRY RUN 🔍" if dry_run else "PAPER TRADE ✅"
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if order and not dry_run:
        order_detail = f"Order `{order.get('order_id','?')}` | {order.get('side','?').upper()} {order.get('qty')} @ market | Status: {order.get('status','?')}"
    elif dry_run and order:
        order_detail = f"Would {order.get('side','?').upper()} {order.get('qty')} shares (dry run)"
    else:
        order_detail = "No order — HOLD position maintained"

    reasoning = decision_text[:500] + "…" if len(decision_text) > 500 else decision_text

    msg = (
        f"## {emoji} **{action}** {ticker} | {mode}\n"
        f"📅 **Date:** {trade_date}\n"
        f"📋 **Order:** {order_detail}\n"
        f"🧠 **Reasoning:** {reasoning}\n"
        f"*CooperCorp 🦅 | {ts}*"
    )
    return _send(CHANNELS["paper_trades"], msg)
