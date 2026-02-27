#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Mac Sleep/Wake Recovery
Detects if the system slept during market hours and reconciles.
Run at system wake via LaunchAgent or caffeinate post-sleep hook.

Also detects missed cron jobs (jobs that should have fired but didn't).
"""
import sys, json, subprocess, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytz

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

ET = pytz.timezone("America/Detroit")
DISCORD_WAR_ROOM = "1469763123010342953"
DISCORD_PAPER_TRADES = "1468597633756037385"


def is_market_hours(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:  # Sat/Sun
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def post_discord(channel: str, msg: str):
    subprocess.run(
        ["openclaw", "message", "send", "--channel", "discord", "--target", channel, "--message", msg],
        capture_output=True
    )


def get_missed_crons(since_minutes: int = 60) -> list:
    """Check OpenClaw cron list for jobs that should have fired but show old lastRunAtMs."""
    try:
        r = subprocess.run(["openclaw", "cron", "list", "--json"], capture_output=True, text=True)
        if r.returncode != 0:
            return []
        data = json.loads(r.stdout)
        jobs = data.get("jobs", [])
        missed = []
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        threshold_ms = since_minutes * 60 * 1000
        for job in jobs:
            if not job.get("enabled"):
                continue
            if "PRJ-002" not in job.get("name", ""):
                continue
            last_run = job.get("state", {}).get("lastRunAtMs", 0)
            next_run = job.get("state", {}).get("nextRunAtMs", 0)
            # If next_run is in the past by > 5 min, job was missed
            if next_run and (now_ms - next_run) > 5 * 60 * 1000:
                missed.append({"name": job["name"], "id": job["id"], "overdue_min": int((now_ms - next_run) / 60000)})
        return missed
    except Exception:
        return []


def main():
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%Y-%m-%d %H:%M ET")

    print(f"Wake recovery check at {now_str}")

    if not is_market_hours(now_et):
        print("Not market hours — no recovery needed")
        return

    # Check for open positions
    try:
        from tradingagents.brokers.alpaca import AlpacaBroker
        broker = AlpacaBroker()
        positions = broker.get_positions()
        has_positions = len(positions) > 0
    except Exception as e:
        print(f"Broker error: {e}")
        has_positions = False
        positions = []

    # Check missed crons
    missed = get_missed_crons(since_minutes=90)

    if missed or has_positions:
        alert_lines = [f"⚠️ WAKE RECOVERY — {now_str}"]

        if missed:
            alert_lines.append(f"\n🔴 {len(missed)} MISSED CRON(S) DETECTED:")
            for m in missed:
                alert_lines.append(f"  • {m['name']} — {m['overdue_min']}min overdue")
            alert_lines.append("→ Re-triggering missed scans...")

        if has_positions:
            alert_lines.append(f"\n📊 {len(positions)} OPEN POSITION(S) during sleep:")
            for p in positions:
                pct = float(p.unrealized_plpc) * 100
                alert_lines.append(f"  • {p.symbol}: {pct:+.2f}% (${float(p.unrealized_pl):.2f})")
            alert_lines.append("→ Reconciling positions now...")

        alert_lines.append("\n— Wake Recovery | CooperCorp PRJ-002")
        msg = "\n".join(alert_lines)
        post_discord(DISCORD_WAR_ROOM, msg)
        post_discord(DISCORD_PAPER_TRADES, msg)
        print(msg)

        # Re-trigger missed scans
        for m in missed:
            try:
                r = subprocess.run(["openclaw", "cron", "trigger", m["id"]], capture_output=True, text=True)
                print(f"Re-triggered: {m['name']} ({r.returncode})")
            except Exception as e:
                print(f"Failed to trigger {m['name']}: {e}")

        # Restart WebSocket stream if it died
        stream_pid = REPO / "logs" / "stream.pid"
        if not stream_pid.exists() and has_positions:
            subprocess.Popen([sys.executable, str(REPO / "scripts" / "stream_manager.py"), "start"])
            print("Stream restarted")
    else:
        print("All clear — no missed crons, no open positions")


if __name__ == "__main__":
    main()
