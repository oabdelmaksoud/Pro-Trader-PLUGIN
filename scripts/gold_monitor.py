#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Gold / XAUUSD Monitor (24/7)
Posts to #gold-xauusd-signals every 30 min with XAUUSD, XAGUSD, DXY signals.

Signal logic:
  - Gold move >0.3% from last post → post update
  - Gold move >0.8%               → ⚡ alert
  - Gold move >1.5%               → 🚨 CRITICAL
  - DXY inverse correlation note when DXY moves >0.3%
  - Quiet hours: 11 PM – 5 AM ET (unless >0.8% gold move)
"""
import sys, os, json, subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Resolve repo root relative to this script — portable across machines
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from tradingagents.dataflows.realtime_quotes import get_quote as rt_quote

GOLD_CHANNEL = "1467907594411704573"
STATE_FILE = REPO_ROOT / "logs" / "gold_state.json"
ET = ZoneInfo("America/New_York")

SYMBOLS = {
    "GC=F":    {"name": "Gold (XAU/USD)",    "emoji": "🥇", "unit": "$/oz",  "threshold": {"watch": 0.3, "alert": 0.8, "critical": 1.5}},
    "SI=F":    {"name": "Silver (XAG/USD)",  "emoji": "🥈", "unit": "$/oz",  "threshold": {"watch": 0.4, "alert": 1.0, "critical": 2.0}},
    "DX-Y.NYB":{"name": "US Dollar (DXY)",   "emoji": "💵", "unit": "index", "threshold": {"watch": 0.2, "alert": 0.5, "critical": 1.0}},
    "TLT":     {"name": "Bonds (TLT)",       "emoji": "📋", "unit": "$",     "threshold": {"watch": 0.3, "alert": 0.7, "critical": 1.5}},
}

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: pass
    return {}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2))

def get_price(symbol):
    try:
        q = rt_quote(symbol)
        if not q or not q.get("price"):
            return None, None, None
        return q["price"], q.get("change_pct", 0.0), None
    except Exception:
        return None, None, None

def signal_emoji(chg, t):
    if abs(chg) >= t["critical"]:  return "🔴" if chg < 0 else "🟢"
    elif abs(chg) >= t["alert"]:   return "🚨" if chg < 0 else "⚡"
    elif abs(chg) >= t["watch"]:   return "📉" if chg < 0 else "📈"
    return "➡️"

def should_post(now_et, data, state, force=False):
    hour = now_et.hour
    quiet = hour >= 23 or hour < 5
    gold_chg = abs(data.get("GC=F", {}).get("chg", 0) or 0)
    if quiet and gold_chg < SYMBOLS["GC=F"]["threshold"]["alert"]:
        return False
    # Always post during active hours
    return True

def build_message(data, now_et):
    time_str = now_et.strftime("%I:%M %p ET, %b %d")

    gold = data.get("GC=F", {})
    dxy  = data.get("DX-Y.NYB", {})

    # Correlation note
    corr_note = ""
    if gold.get("chg") and dxy.get("chg"):
        if gold["chg"] > 0.3 and dxy["chg"] < -0.2:
            corr_note = "📌 Classic inverse: Gold ↑ + DXY ↓ — dollar weakness driving safe haven demand"
        elif gold["chg"] < -0.3 and dxy["chg"] > 0.2:
            corr_note = "📌 Classic inverse: Gold ↓ + DXY ↑ — dollar strength pressuring gold"
        elif gold["chg"] > 0.3 and dxy["chg"] > 0.2:
            corr_note = "⚠️ Unusual: Gold ↑ AND DXY ↑ — fear/geopolitical bid overriding dollar correlation"

    # Bias
    gold_chg = gold.get("chg", 0) or 0
    if gold_chg >= 1.5:    bias = "🟢 STRONG BULLISH — potential breakout"
    elif gold_chg >= 0.5:  bias = "📈 Bullish"
    elif gold_chg <= -1.5: bias = "🔴 STRONG BEARISH — potential breakdown"
    elif gold_chg <= -0.5: bias = "📉 Bearish"
    else:                  bias = "➡️ Neutral — consolidating"

    lines = [
        f"**🥇 GOLD & METALS — {time_str}**",
        f"Bias: {bias}",
        "",
    ]

    for sym, info in SYMBOLS.items():
        d = data.get(sym, {})
        if not d.get("price"):
            lines.append(f"  {info['emoji']} **{info['name']}** — unavailable")
            continue
        t = info["threshold"]
        sig = signal_emoji(d["chg"], t)
        chg_str = f"+{d['chg']:.2f}%" if d["chg"] >= 0 else f"{d['chg']:.2f}%"
        chg5_str = ""
        if d.get("chg_5d") is not None:
            chg5_str = f" | 5d: {'+' if d['chg_5d']>=0 else ''}{d['chg_5d']:.1f}%"
        price_str = f"${d['price']:,.2f}"
        lines.append(f"  {sig} **{info['name']}** {price_str} ({chg_str}{chg5_str})")

    if corr_note:
        lines.append("")
        lines.append(corr_note)

    # Critical alerts
    for sym, d in data.items():
        if not d.get("price"): continue
        t = SYMBOLS[sym]["threshold"]
        if abs(d["chg"]) >= t["critical"]:
            direction = "SURGE" if d["chg"] > 0 else "SELLOFF"
            lines.append(f"")
            lines.append(f"🚨 **{SYMBOLS[sym]['name']} {direction} {abs(d['chg']):.1f}%** — significant intraday move")

    # Key levels for gold
    if gold.get("price"):
        gp = gold["price"]
        r1 = round(gp * 1.005, 1)
        s1 = round(gp * 0.995, 1)
        lines.append("")
        lines.append(f"**Key Levels (Gold):** S1 ${s1:,.1f} | Current ${gp:,.2f} | R1 ${r1:,.1f}")

    lines.append("")
    lines.append("*24/7 gold & metals monitor | CooperCorp PRJ-002*")
    return "\n".join(lines)

def post_to_discord(msg):
    result = subprocess.run(
        ["openclaw", "message", "send",
         "--channel", "discord",
         "--target", GOLD_CHANNEL,
         "--message", msg],
        capture_output=True, text=True
    )
    return result.returncode == 0

def main():
    now_et = datetime.now(ET)
    state  = load_state()
    force  = "--force" in sys.argv

    data = {}
    for sym in SYMBOLS:
        result = get_price(sym)
        if len(result) == 3:
            price, chg, chg_5d = result
        else:
            price, chg = result; chg_5d = None
        data[sym] = {"price": price, "chg": chg or 0.0, "chg_5d": chg_5d}

    if not should_post(now_et, data, state, force=force):
        print(f"[gold_monitor] Silent pass at {now_et.strftime('%H:%M ET')}")
        return

    msg = build_message(data, now_et)
    ok  = post_to_discord(msg)

    if ok:
        new_state = {sym: {"price": d["price"], "ts": now_et.isoformat()} for sym, d in data.items()}
        save_state(new_state)
        print(f"[gold_monitor] Posted at {now_et.strftime('%H:%M ET')}")
    else:
        print(f"[gold_monitor] Discord post failed")

if __name__ == "__main__":
    main()
