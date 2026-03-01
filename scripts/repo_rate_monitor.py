"""
repo_rate_monitor.py — Repo rate / SOFR liquidity stress monitor
Runs daily at 9 AM ET.
Fetches SOFR and EFFR from NY Fed. Alerts on SOFR spike >50bps.
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, date

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import requests
except ImportError:
    requests = None

DISCORD_CHANNEL = "1469763123010342953"
LOGS_DIR = REPO / "logs"
LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = LOGS_DIR / "repo_rates.json"

SOFR_URL = "https://markets.newyorkfed.org/api/rates/sofr/last/1.json"
EFFR_URL = "https://markets.newyorkfed.org/api/rates/effr/last/1.json"

SPIKE_THRESHOLD_BPS = 50  # 0.50%


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[repo_rate_monitor] Discord post failed: {e}")


def load_history() -> dict:
    try:
        if OUTPUT_FILE.exists():
            return json.loads(OUTPUT_FILE.read_text())
    except Exception:
        pass
    return {"sofr": [], "effr": [], "alerts": []}


def save_history(history: dict) -> None:
    try:
        OUTPUT_FILE.write_text(json.dumps(history, indent=2))
    except Exception as e:
        print(f"[repo_rate_monitor] Failed to save history: {e}")


def fetch_rate(url: str) -> float | None:
    if not requests:
        return None
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        refRates = data.get("refRates", [])
        if refRates:
            return float(refRates[0].get("percentRate", 0))
        return None
    except Exception as e:
        print(f"[repo_rate_monitor] Fetch error from {url}: {e}")
        return None


def calc_30d_avg(history_list: list) -> float | None:
    recent = history_list[-30:]
    if not recent:
        return None
    rates = [entry.get("rate") for entry in recent if entry.get("rate") is not None]
    return sum(rates) / len(rates) if rates else None


def main():
    sofr = fetch_rate(SOFR_URL)
    effr = fetch_rate(EFFR_URL)
    now_iso = datetime.utcnow().isoformat()

    print(f"[repo_rate_monitor] SOFR: {sofr}% | EFFR: {effr}%")

    history = load_history()

    if sofr is not None:
        history["sofr"].append({"date": now_iso, "rate": sofr})
        history["sofr"] = history["sofr"][-60:]  # Keep 60 days max

    if effr is not None:
        history["effr"].append({"date": now_iso, "rate": effr})
        history["effr"] = history["effr"][-60:]

    # Check SOFR spike
    if sofr is not None and len(history["sofr"]) >= 2:
        avg_30d = calc_30d_avg(history["sofr"][:-1])  # Exclude today
        if avg_30d is not None:
            spike_bps = (sofr - avg_30d) * 100
            print(f"[repo_rate_monitor] SOFR 30d avg: {avg_30d:.3f}% | Spike: {spike_bps:.1f}bps")

            if spike_bps > SPIKE_THRESHOLD_BPS:
                msg = (
                    f"⚠️ LIQUIDITY STRESS — SOFR spike\n"
                    f"SOFR: {sofr:.3f}% (30d avg: {avg_30d:.3f}%)\n"
                    f"Spike: +{spike_bps:.0f}bps above 30-day average\n"
                    f"📉 Risk-off signal: reduce equity exposure\n"
                    f"— Cooper 🦅"
                )
                print(msg)
                post_to_discord(msg)
                history.setdefault("alerts", []).append({
                    "date": now_iso, "sofr": sofr, "avg": avg_30d, "spike_bps": spike_bps
                })

    save_history(history)


if __name__ == "__main__":
    main()
