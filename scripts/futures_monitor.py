"""
futures_monitor.py — Sunday night futures pre-week bias monitor
Runs at 6:05 PM ET Sunday via cron.
Posts formatted pre-week bias card to Discord war-room.
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import yfinance as yf
except ImportError:
    yf = None

DISCORD_CHANNEL = "1469763123010342953"

FUTURES = {
    "ES=F": "ES (S&P)",
    "NQ=F": "NQ (Nasdaq)",
    "CL=F": "CL (Oil)",
    "GC=F": "GC (Gold)",
    "YM=F": "YM (Dow)",
}

# Micro futures affordable on $500 account (margin < $700)
MICRO_FUTURES = {
    "ETH=F":  {"label": "Micro Ether (/MET)",    "margin": 77},
    "CAD=X":  {"label": "Micro CAD (/MCD)",       "margin": 110},
    "AUD=X":  {"label": "Micro AUD (/M6A)",       "margin": 209},
    "GBP=X":  {"label": "Micro GBP (/M6B)",       "margin": 220},
    "EUR=X":  {"label": "Micro EUR (/M6E)",       "margin": 297},
    "BTC=F":  {"label": "Bitcoin Friday (/BFF)",   "margin": 365},
    "GC=F":   {"label": "1oz Gold (/1OZ)",         "margin": 472},
    "CHF=X":  {"label": "Micro CHF (/MSF)",        "margin": 495},
    "NG=F":   {"label": "Micro NatGas (/MNG)",     "margin": 633},
}


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[futures_monitor] Discord post failed: {e}")


def get_future_data(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        price = info.get("regularMarketPrice") or info.get("previousClose") or 0
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose") or price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
        return {"price": price, "change_pct": change_pct, "ok": True}
    except Exception as e:
        print(f"[futures_monitor] Error fetching {symbol}: {e}")
        return {"price": 0, "change_pct": 0, "ok": False}


def classify_bias(changes: list) -> str:
    avg = sum(changes) / len(changes) if changes else 0
    if avg > 1.0:
        return "BULLISH"
    elif avg < -1.0:
        return "BEARISH"
    return "NEUTRAL"


def main():
    if yf is None:
        print("[futures_monitor] yfinance not available — aborting")
        return

    geopolitical = any("iran" in arg.lower() for arg in sys.argv[1:])
    today_str = datetime.now().strftime("%Y-%m-%d")
    results = {}

    for symbol, label in FUTURES.items():
        results[symbol] = {"label": label, **get_future_data(symbol)}

    changes = [r["change_pct"] for r in results.values() if r["ok"]]
    bias = classify_bias(changes)
    bias_emoji = "🟢" if bias == "BULLISH" else ("🔴" if bias == "BEARISH" else "⚪")

    lines = [
        f"🌙 SUNDAY FUTURES OPEN — {today_str}",
        f"{bias_emoji} Bias: {bias}",
        "",
    ]

    for symbol, data in results.items():
        label = data["label"]
        price = data["price"]
        pct = data["change_pct"]
        sign = "+" if pct >= 0 else ""
        lines.append(f"{label}: {price:.2f} {sign}{pct:.2f}%")

    lines.append("")
    lines.append("🎯 Monday Setup:")

    if bias == "BULLISH":
        lines.append("Tech/growth long bias. Watch NVDA, MSFT, AMD.")
    elif bias == "BEARISH":
        lines.append("Defensive positioning. Watch GLD, TLT, XOM.")
    else:
        lines.append("Mixed signals. Wait for market open confirmation.")

    if geopolitical:
        lines.append("⚠️ Geopolitical premium: Long energy/defense.")

    # Micro futures scan for $500 account
    lines.append("")
    lines.append("📊 Micro Futures (affordable on $500):")
    micro_movers = []
    for symbol, info in MICRO_FUTURES.items():
        mdata = get_future_data(symbol)
        if mdata["ok"] and abs(mdata["change_pct"]) > 0.3:
            sign = "+" if mdata["change_pct"] >= 0 else ""
            micro_movers.append((info["label"], mdata["change_pct"], info["margin"]))
            lines.append(f"  {info['label']}: {sign}{mdata['change_pct']:.2f}% (margin: ${info['margin']})")
    if not micro_movers:
        lines.append("  No significant micro futures moves yet.")

    lines.append("")
    lines.append("— Cooper 🦅 | Pre-Week Brief")

    msg = "\n".join(lines)
    print(msg)
    post_to_discord(msg)


if __name__ == "__main__":
    main()
