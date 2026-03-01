"""
economic_calendar.py — Economic release monitor
Runs hourly during market hours.
Posts 60-min warnings for high-impact macro events.
"""

import sys
import json
import subprocess
import os
from pathlib import Path
from datetime import datetime, timedelta, date

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
CACHE_FILE = LOGS_DIR / "econ_calendar_cache.json"

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")

HIGH_IMPACT_KEYWORDS = ["CPI", "PPI", "FOMC", "NFP", "GDP", "Retail Sales", "PCE", "Non-Farm"]

IMPACT_DESCRIPTIONS = {
    "CPI": "Inflation print — high CPI = hawkish Fed risk, equity selloff, USD up",
    "PPI": "Producer price inflation — leading indicator for CPI",
    "FOMC": "Fed rate decision — market-moving event, expect high volatility",
    "NFP": "Jobs data — strong = Fed hawkish, weak = dovish, risk-on/off",
    "GDP": "Economic growth — miss = recession fears, beat = risk-on",
    "Retail Sales": "Consumer spending — drives 70% of GDP",
    "PCE": "Fed's preferred inflation metric — drives rate expectations",
    "Non-Farm": "Non-farm payrolls — same as NFP signal",
}


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[economic_calendar] Discord post failed: {e}")


def load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception:
        pass
    return {"posted": []}


def save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception as e:
        print(f"[economic_calendar] Cache save failed: {e}")


def fetch_economic_calendar(today_str: str) -> list:
    if not requests or not FINNHUB_KEY:
        print("[economic_calendar] requests or FINNHUB_API_KEY not available")
        return []
    try:
        url = f"https://finnhub.io/api/v1/calendar/economic?from={today_str}&to={today_str}&token={FINNHUB_KEY}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("economicCalendar", [])
    except Exception as e:
        print(f"[economic_calendar] Finnhub fetch failed: {e}")
        return []


def is_high_impact(event_name: str) -> bool:
    for kw in HIGH_IMPACT_KEYWORDS:
        if kw.lower() in event_name.lower():
            return True
    return False


def get_impact_desc(event_name: str) -> str:
    for kw, desc in IMPACT_DESCRIPTIONS.items():
        if kw.lower() in event_name.lower():
            return desc
    return "Major macro release — expect volatility"


def main():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    now = datetime.utcnow()

    events = fetch_economic_calendar(today_str)
    cache = load_cache()
    posted_ids = set(cache.get("posted", []))

    for event in events:
        try:
            name = event.get("event", "Unknown")
            if not is_high_impact(name):
                continue

            event_time_str = event.get("time", "")
            expected = event.get("estimate", "N/A")
            prior = event.get("prev", "N/A")

            # Parse event time
            try:
                event_dt = datetime.strptime(f"{today_str} {event_time_str}", "%Y-%m-%d %H:%M")
            except Exception:
                continue

            minutes_until = (event_dt - now).total_seconds() / 60
            event_id = f"{today_str}_{name}_{event_time_str}"

            if 55 <= minutes_until <= 65 and event_id not in posted_ids:
                impact_desc = get_impact_desc(name)
                msg = (
                    f"⏰ MACRO RELEASE IN 60 MIN — {name}\n"
                    f"Expected: {expected} | Prior: {prior}\n"
                    f"⚡ Impact: {impact_desc}\n"
                    f"— Cooper 🦅"
                )
                print(msg)
                post_to_discord(msg)
                posted_ids.add(event_id)
        except Exception as e:
            print(f"[economic_calendar] Event processing error: {e}")

    cache["posted"] = list(posted_ids)
    save_cache(cache)


if __name__ == "__main__":
    main()
