"""
earnings_calendar.py — Daily earnings pre-positioning scanner
Runs at 4 PM ET weekdays.
Fetches upcoming earnings from Finnhub and posts alerts to Discord war-room.
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

WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AMD", "TSLA",
    "PLTR", "CRWD", "ARM", "MSTR", "XOM", "CVX", "LMT", "RTX", "JPM", "LLY", "PFE"
]

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[earnings_calendar] Discord post failed: {e}")


def fetch_earnings(from_date: str, to_date: str) -> list:
    if not requests or not FINNHUB_KEY:
        print("[earnings_calendar] requests or FINNHUB_API_KEY not available")
        return []
    try:
        url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&token={FINNHUB_KEY}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("earningsCalendar", [])
    except Exception as e:
        print(f"[earnings_calendar] Finnhub fetch failed: {e}")
        return []


def main():
    today = date.today()
    to_date = today + timedelta(days=2)
    from_str = today.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")

    all_earnings = fetch_earnings(from_str, to_str)
    upcoming = []
    past_results = []

    for e in all_earnings:
        symbol = (e.get("symbol") or "").upper()
        if symbol not in WATCHLIST:
            continue

        report_date_str = e.get("date", "")
        try:
            report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
        except Exception:
            continue

        eps_est = e.get("epsEstimate")
        eps_actual = e.get("epsActual")
        rev_est = e.get("revenueEstimate")
        hour = e.get("hour", "")
        timing = "AMC" if hour == "amc" else ("BMO" if hour == "bmo" else hour.upper())

        if report_date >= today:
            upcoming.append({
                "symbol": symbol, "date": report_date_str,
                "timing": timing, "eps_est": eps_est, "rev_est": rev_est
            })
            rev_b = f"{rev_est / 1e9:.2f}" if rev_est else "N/A"
            eps_str = f"${eps_est:.2f}" if eps_est is not None else "N/A"
            pre_date = (report_date - timedelta(days=1)).strftime("%Y-%m-%d")
            msg = (
                f"🗓️ EARNINGS ALERT — {symbol} {report_date_str} {timing}\n"
                f"EPS est: {eps_str} | Rev est: ${rev_b}B\n"
                f"⚡ Pre-position window: {pre_date} during market hours\n"
                f"— Cooper 🦅"
            )
            print(msg)
            post_to_discord(msg)

        elif report_date < today and eps_est is not None and eps_actual is not None:
            try:
                beat_pct = ((eps_actual - eps_est) / abs(eps_est)) * 100 if eps_est != 0 else 0
                if beat_pct > 5:
                    msg = (
                        f"📈 EARNINGS BEAT — {symbol} {report_date_str}\n"
                        f"EPS actual: ${eps_actual:.2f} vs est: ${eps_est:.2f} (+{beat_pct:.1f}%)\n"
                        f"— Cooper 🦅"
                    )
                    print(msg)
                    post_to_discord(msg)
                elif beat_pct < -5:
                    msg = (
                        f"📉 EARNINGS MISS — {symbol} {report_date_str}\n"
                        f"EPS actual: ${eps_actual:.2f} vs est: ${eps_est:.2f} ({beat_pct:.1f}%)\n"
                        f"— Cooper 🦅"
                    )
                    print(msg)
                    post_to_discord(msg)
            except Exception as ex:
                print(f"[earnings_calendar] Beat/miss calc error for {symbol}: {ex}")

    out_path = LOGS_DIR / "upcoming_earnings.json"
    try:
        with open(out_path, "w") as f:
            json.dump({"updated": datetime.utcnow().isoformat(), "earnings": upcoming}, f, indent=2)
        print(f"[earnings_calendar] Wrote {len(upcoming)} upcoming earnings to {out_path}")
    except Exception as e:
        print(f"[earnings_calendar] Failed to write log: {e}")


if __name__ == "__main__":
    main()
