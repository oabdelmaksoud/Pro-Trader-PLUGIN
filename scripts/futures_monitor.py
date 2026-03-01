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

    lines.append("")
    lines.append("— Cooper 🦅 | Pre-Week Brief")

    msg = "\n".join(lines)
    print(msg)
    post_to_discord(msg)


if __name__ == "__main__":
    main()
