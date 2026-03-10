"""Futures Monitor Plugin — wraps scripts/futures_monitor.py."""

from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

from pro_trader.core.interfaces import MonitorPlugin

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO))


class FuturesMonitorPlugin(MonitorPlugin):
    name = "futures_monitor"
    version = "1.0.0"
    description = "Futures session times, margin changes, and contract rollovers"
    interval = 900  # 15 minutes

    def __init__(self):
        self._state_path = Path("logs/futures_state.json")
        self._account_value = 500

    def configure(self, config: dict) -> None:
        self._account_value = config.get("account_value", 500)

    def check(self) -> list[dict]:
        alerts = []
        try:
            from tradingagents.dataflows.futures_data import (
                get_affordable_contracts, MICRO_FUTURES, get_session_hours
            )
        except ImportError:
            return alerts

        affordable = get_affordable_contracts(self._account_value, margin_buffer=1.5)
        state = {
            "account_value": self._account_value,
            "affordable_count": len(affordable),
            "affordable": [c["root"] for c in affordable],
            "total_contracts": len(MICRO_FUTURES),
        }

        # Check for margin changes vs last run
        if self._state_path.exists():
            try:
                prev = json.loads(self._state_path.read_text())
                prev_affordable = set(prev.get("affordable", []))
                curr_affordable = set(state["affordable"])

                lost = prev_affordable - curr_affordable
                gained = curr_affordable - prev_affordable

                if lost:
                    alerts.append({
                        "type": "margin_change",
                        "severity": "warning",
                        "message": f"Contracts no longer affordable: {', '.join(lost)}",
                        "data": {"lost": list(lost)},
                    })
                if gained:
                    alerts.append({
                        "type": "margin_change",
                        "severity": "info",
                        "message": f"New contracts now affordable: {', '.join(gained)}",
                        "data": {"gained": list(gained)},
                    })
            except Exception:
                pass

        # Persist
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(state, indent=2))
        except Exception:
            pass

        return alerts

    def get_state(self) -> dict:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except Exception:
                pass
        return {}
