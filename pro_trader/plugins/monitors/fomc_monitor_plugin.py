"""FOMC Monitor Plugin — wraps scripts/fomc_monitor.py."""

from __future__ import annotations
import json
import logging
from datetime import date, datetime
from pathlib import Path

from pro_trader.core.interfaces import MonitorPlugin

logger = logging.getLogger(__name__)

# 2025-2026 FOMC meeting dates
FOMC_DATES = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


class FOMCMonitorPlugin(MonitorPlugin):
    name = "fomc"
    version = "1.0.0"
    description = "FOMC meeting proximity monitor"
    interval = 3600  # hourly

    def __init__(self):
        self._state_path = Path("logs/fomc_state.json")

    def check(self) -> list[dict]:
        alerts = []
        today = date.today()
        next_meeting = None
        days_until = None

        for d in FOMC_DATES:
            meeting = date.fromisoformat(d)
            if meeting >= today:
                next_meeting = meeting
                days_until = (meeting - today).days
                break

        if next_meeting is None:
            return alerts

        state = {
            "next_meeting": str(next_meeting),
            "days_until_next": days_until,
            "updated": datetime.now().isoformat(),
        }

        # Persist
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(state, indent=2))
        except Exception:
            pass

        if days_until <= 2:
            alerts.append({
                "type": "fomc_proximity",
                "severity": "warning",
                "message": f"FOMC meeting in {days_until} day(s) ({next_meeting}) — high volatility risk",
                "data": state,
            })
        elif days_until <= 5:
            alerts.append({
                "type": "fomc_proximity",
                "severity": "info",
                "message": f"FOMC meeting in {days_until} days ({next_meeting})",
                "data": state,
            })

        return alerts

    def get_state(self) -> dict:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except Exception:
                pass
        return {}
