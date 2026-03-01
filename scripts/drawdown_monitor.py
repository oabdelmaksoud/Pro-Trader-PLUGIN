"""
drawdown_monitor.py — Portfolio-level drawdown circuit breaker
Runs every 15 min during market hours.
Halts new entries if portfolio drops 5%+ from daily high watermark.

NOTE: trade_gate.py must check logs/drawdown_state.json before executing any trade.
If halted=true, do NOT submit new orders.
"""

import sys
import json
import subprocess
import os
from pathlib import Path
from datetime import datetime, date

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass

DISCORD_CHANNEL = "1469763123010342953"
LOGS_DIR = REPO / "logs"
LOGS_DIR.mkdir(exist_ok=True)
STATE_FILE = LOGS_DIR / "drawdown_state.json"

ALPACA_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE = "https://paper-api.alpaca.markets"

HALT_THRESHOLD = 0.95   # 5% drawdown triggers halt
RESUME_THRESHOLD = 0.97  # recover to <3% to resume


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[drawdown_monitor] Discord post failed: {e}")


def load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"[drawdown_monitor] State save failed: {e}")


def get_portfolio_value() -> float | None:
    if not requests or not ALPACA_KEY:
        print("[drawdown_monitor] Alpaca credentials missing — skipping")
        return None
    try:
        url = f"{ALPACA_BASE}/v2/account"
        headers = {
            "APCA-API-KEY-ID": ALPACA_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET,
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("portfolio_value", 0))
    except Exception as e:
        print(f"[drawdown_monitor] Alpaca API error: {e}")
        return None


def main():
    today_str = date.today().strftime("%Y-%m-%d")
    state = load_state()

    # Reset watermark on new trading day
    if state.get("date") != today_str:
        state = {"date": today_str, "high_watermark": 0, "current": 0,
                 "drawdown_pct": 0, "halted": False}

    current = get_portfolio_value()
    if current is None:
        print("[drawdown_monitor] Could not get portfolio value — exiting")
        return

    high_watermark = max(state.get("high_watermark", current), current)
    drawdown_pct = ((high_watermark - current) / high_watermark * 100) if high_watermark > 0 else 0
    was_halted = state.get("halted", False)

    state.update({
        "date": today_str,
        "high_watermark": high_watermark,
        "current": current,
        "drawdown_pct": round(drawdown_pct, 3),
        "last_checked": datetime.utcnow().isoformat(),
    })

    print(f"[drawdown_monitor] Value: ${current:,.2f} | High: ${high_watermark:,.2f} | Drawdown: {drawdown_pct:.2f}%")

    if current < high_watermark * HALT_THRESHOLD and not was_halted:
        state["halted"] = True
        msg = (
            f"🚨 CIRCUIT BREAKER TRIGGERED\n"
            f"📉 Portfolio down 5%+ today\n"
            f"🛑 NEW ENTRIES HALTED\n"
            f"Value: ${current:,.2f} | High: ${high_watermark:,.2f} | Drawdown: {drawdown_pct:.2f}%\n"
            f"— Cooper 🦅"
        )
        print(msg)
        post_to_discord(msg)

    elif was_halted and current >= high_watermark * RESUME_THRESHOLD:
        state["halted"] = False
        msg = (
            f"✅ CIRCUIT BREAKER RESET\n"
            f"📈 Portfolio recovered to <3% drawdown\n"
            f"✅ NEW ENTRIES ALLOWED\n"
            f"Value: ${current:,.2f} | Drawdown: {drawdown_pct:.2f}%\n"
            f"— Cooper 🦅"
        )
        print(msg)
        post_to_discord(msg)

    save_state(state)


if __name__ == "__main__":
    main()
