"""
fomc_monitor.py — Fed FOMC calendar and pre-positioning monitor
Runs daily. Posts 3-day warnings and day-of reminders.
"""

import sys
import json
import subprocess
import os
from pathlib import Path
from datetime import datetime, date, timedelta

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
STATE_FILE = LOGS_DIR / "fomc_state.json"

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")

# 2026 FOMC meeting dates (second day = decision day)
FOMC_2026 = [
    "2026-01-29", "2026-03-19", "2026-04-30", "2026-06-11",
    "2026-07-30", "2026-09-17", "2026-10-29", "2026-12-10"
]

# 2025 FOMC dates for completeness
FOMC_2025 = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10"
]


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[fomc_monitor] Discord post failed: {e}")


def load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {"posted_alerts": []}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"[fomc_monitor] State save failed: {e}")


def fetch_fomc_from_finnhub(today: date) -> list:
    """Try to get FOMC dates from Finnhub economic calendar."""
    if not requests or not FINNHUB_KEY:
        return []
    try:
        from_str = today.strftime("%Y-%m-%d")
        to_str = (today + timedelta(days=90)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/calendar/economic?from={from_str}&to={to_str}&token={FINNHUB_KEY}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        events = data.get("economicCalendar", [])
        fomc_dates = []
        for e in events:
            name = (e.get("event") or "").lower()
            if "fomc" in name or "fed" in name and "rate" in name:
                dt_str = e.get("time", "")[:10]
                if dt_str:
                    fomc_dates.append(dt_str)
        return fomc_dates
    except Exception as e:
        print(f"[fomc_monitor] Finnhub FOMC fetch failed: {e}")
        return []


def get_fed_watch_signal() -> str:
    """Get CME FedWatch cut probability (graceful fallback)."""
    # FedWatch doesn't have a free public API — return neutral by default
    # In production, parse from CME website or use a data provider
    return "hold"  # "cut", "hike", or "hold"


def main():
    today = date.today()
    state = load_state()
    posted = set(state.get("posted_alerts", []))

    # Combine Finnhub + hardcoded dates
    finnhub_dates = fetch_fomc_from_finnhub(today)
    all_fomc = list(set(FOMC_2025 + FOMC_2026 + finnhub_dates))
    all_fomc.sort()

    now_hour_utc = datetime.utcnow().hour  # FOMC at 2 PM ET = 19:00 UTC

    for fomc_str in all_fomc:
        try:
            fomc_date = datetime.strptime(fomc_str, "%Y-%m-%d").date()
            days_until = (fomc_date - today).days

            # 3-day pre-warning
            if days_until == 3:
                alert_id = f"preposition_{fomc_str}"
                if alert_id not in posted:
                    fed_signal = get_fed_watch_signal()
                    if fed_signal == "cut":
                        positioning = "Cut likely → Long TLT/GLD, Long growth stocks"
                    elif fed_signal == "hike":
                        positioning = "Hike likely → Short TLT, defensive positioning"
                    else:
                        positioning = "Hold expected → Watch for surprise guidance changes"

                    msg = (
                        f"📅 FOMC IN 3 DAYS — {fomc_str}\n"
                        f"🎯 Pre-position window open\n"
                        f"{positioning}\n"
                        f"— Cooper 🦅"
                    )
                    print(msg)
                    post_to_discord(msg)
                    posted.add(alert_id)

            # Day-of 1-hour reminder (post at ~18:00 UTC = 1 PM ET)
            elif days_until == 0 and 17 <= now_hour_utc <= 19:
                alert_id = f"dayof_{fomc_str}_{datetime.utcnow().strftime('%H')}"
                if alert_id not in posted:
                    msg = (
                        f"⏰ FOMC DECISION IN ~1 HOUR — {fomc_str}\n"
                        f"📢 Rate announcement at 2:00 PM ET\n"
                        f"⚡ Expect high volatility. Tighten stops.\n"
                        f"— Cooper 🦅"
                    )
                    print(msg)
                    post_to_discord(msg)
                    posted.add(alert_id)

        except Exception as e:
            print(f"[fomc_monitor] Error processing {fomc_str}: {e}")

    state["posted_alerts"] = list(posted)
    state["last_run"] = datetime.utcnow().isoformat()
    state["next_fomc"] = next(
        (f for f in all_fomc if datetime.strptime(f, "%Y-%m-%d").date() >= today), None
    )
    save_state(state)
    print(f"[fomc_monitor] Next FOMC: {state.get('next_fomc')}")


if __name__ == "__main__":
    main()
