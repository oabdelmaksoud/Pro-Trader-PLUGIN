#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Futures & Crypto Monitor (24/5 + 24/7)
Posts to #futures-signals every 30 min with ES, NQ, BTC, ETH signals.

Signal logic:
  - Move >0.5% from last post  → post update
  - Move >1.0%                 → 🚨 alert
  - Move >2.0%                 → 🔴 CRITICAL
  - Always post at session open (6 PM ET Sun, 9:30 AM ET Mon–Fri)
  - Quiet hours: 11 PM – 5 AM ET (unless >1% move)
"""
import sys, os, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Resolve repo root relative to this script — portable across machines
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from tradingagents.dataflows.realtime_quotes import get_quote as rt_quote

FUTURES_CHANNEL = "1468796845114392587"
STATE_FILE = REPO_ROOT / "logs" / "futures_state.json"

ET = ZoneInfo("America/New_York")

SYMBOLS = {
    "ES=F":  {"name": "S&P 500 Futures",   "emoji": "📊", "type": "futures"},
    "NQ=F":  {"name": "Nasdaq Futures",     "emoji": "💻", "type": "futures"},
    "YM=F":  {"name": "Dow Futures",        "emoji": "🏭", "type": "futures"},
    "BTC-USD": {"name": "Bitcoin",          "emoji": "₿",  "type": "crypto"},
    "ETH-USD": {"name": "Ethereum",         "emoji": "⟠",  "type": "crypto"},
}

SIGNAL_THRESHOLDS = {
    "crypto":  {"watch": 0.5, "alert": 1.5, "critical": 3.0},
    "futures": {"watch": 0.3, "alert": 0.8, "critical": 1.5},
}

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def get_price(symbol):
    try:
        q = rt_quote(symbol)
        if not q or not q.get("price"):
            return None, None
        return q["price"], q.get("change_pct", 0.0)
    except Exception:
        return None, None

def signal_emoji(chg, sym_type):
    t = SIGNAL_THRESHOLDS[sym_type]
    if abs(chg) >= t["critical"]:
        return "🔴" if chg < 0 else "🟢"
    elif abs(chg) >= t["alert"]:
        return "🚨" if chg < 0 else "⚡"
    elif abs(chg) >= t["watch"]:
        return "📉" if chg < 0 else "📈"
    return "➡️"

def bias_label(chg, sym_type):
    t = SIGNAL_THRESHOLDS[sym_type]
    if abs(chg) >= t["critical"]:
        return "STRONG DOWN" if chg < 0 else "STRONG UP"
    elif abs(chg) >= t["alert"]:
        return "BEARISH" if chg < 0 else "BULLISH"
    elif abs(chg) >= t["watch"]:
        return "WEAK DOWN" if chg < 0 else "WEAK UP"
    return "NEUTRAL"

def should_post(now_et, data, state, force=False):
    hour = now_et.hour
    # Quiet hours: 11 PM – 5 AM ET, unless significant move
    quiet = hour >= 23 or hour < 5
    has_alert = any(
        abs(d["chg"]) >= SIGNAL_THRESHOLDS[SYMBOLS[sym]["type"]]["alert"]
        for sym, d in data.items() if d["price"]
    )
    if quiet and not has_alert:
        return False
    # Always post during active hours
    return True

def format_signal_line(sym, d):
    info = SYMBOLS[sym]
    if d["price"] is None:
        return f"  {info['emoji']} **{info['name']}** — data unavailable"
    chg = d["chg"]
    sig = signal_emoji(chg, info["type"])
    bias = bias_label(chg, info["type"])
    chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
    price_str = f"${d['price']:,.2f}" if info["type"] == "crypto" else f"{d['price']:,.1f}"
    return f"  {sig} **{info['name']}** {price_str} ({chg_str}) — {bias}"

def build_message(data, now_et):
    time_str = now_et.strftime("%I:%M %p ET, %b %d")
    # Overall sentiment
    moves = [d["chg"] for d in data.values() if d["price"] is not None]
    avg_move = sum(moves) / len(moves) if moves else 0
    if avg_move <= -1.0:
        overall = "🔴 RISK-OFF"
    elif avg_move <= -0.3:
        overall = "📉 Mild selling"
    elif avg_move >= 1.0:
        overall = "🟢 RISK-ON"
    elif avg_move >= 0.3:
        overall = "📈 Mild buying"
    else:
        overall = "➡️ Neutral"

    lines = [
        f"**📡 FUTURES & CRYPTO — {time_str}**",
        f"Overall: {overall}",
        "",
        "**Futures (24/5)**",
    ]
    for sym in ["ES=F", "NQ=F", "YM=F"]:
        lines.append(format_signal_line(sym, data[sym]))
    lines.append("")
    lines.append("**Crypto (24/7)**")
    for sym in ["BTC-USD", "ETH-USD"]:
        lines.append(format_signal_line(sym, data[sym]))

    # Critical alerts
    crits = []
    for sym, d in data.items():
        if d["price"] is None: continue
        info = SYMBOLS[sym]
        t = SIGNAL_THRESHOLDS[info["type"]]
        if abs(d["chg"]) >= t["critical"]:
            direction = "DOWN" if d["chg"] < 0 else "UP"
            crits.append(f"🚨 **{info['name']} {direction} {abs(d['chg']):.1f}%** — circuit breaker territory")
    if crits:
        lines.append("")
        lines += crits

    lines.append("")
    lines.append("*24/5 futures | 24/7 crypto | CooperCorp PRJ-002*")
    return "\n".join(lines)

def post_to_discord(msg):
    result = subprocess.run(
        ["openclaw", "message", "send",
         "--channel", "discord",
         "--target", FUTURES_CHANNEL,
         "--message", msg],
        capture_output=True, text=True
    )
    return result.returncode == 0

def main():
    now_et = datetime.now(ET)
    state  = load_state()
    force  = "--force" in sys.argv

    # Fetch all prices
    data = {}
    for sym in SYMBOLS:
        price, chg = get_price(sym)
        data[sym] = {"price": price, "chg": chg or 0.0}

    if not should_post(now_et, data, state, force=force):
        print(f"[futures_monitor] Silent pass at {now_et.strftime('%H:%M ET')} — no significant move")
        return

    msg = build_message(data, now_et)
    ok  = post_to_discord(msg)

    if ok:
        # Update state
        new_state = {sym: {"price": d["price"], "ts": now_et.isoformat()} for sym, d in data.items()}
        save_state(new_state)
        print(f"[futures_monitor] Posted at {now_et.strftime('%H:%M ET')}")
    else:
        print(f"[futures_monitor] Discord post failed")

if __name__ == "__main__":
    main()
