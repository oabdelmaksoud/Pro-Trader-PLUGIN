"""
CooperCorp PRJ-002 — Trailing Stop Manager
Tracks high-water mark for each position and computes dynamic stop.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

HWM_FILE = Path(__file__).parent.parent.parent / "logs" / "hwm.json"


class TrailingStopManager:
    """
    Maintains per-symbol high-water marks.
    Trail stop: 3% below highest price reached since entry.
    """
    def __init__(self, trail_pct: float = 0.03):
        self.trail_pct = trail_pct
        self._data = self._load()

    def _load(self):
        if HWM_FILE.exists():
            try:
                return json.loads(HWM_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        HWM_FILE.parent.mkdir(parents=True, exist_ok=True)
        HWM_FILE.write_text(json.dumps(self._data, indent=2))

    def update(self, symbol: str, current_price: float) -> float:
        """
        Update HWM with current price. Returns current trailing stop price.
        """
        sym = symbol.upper()
        if sym not in self._data:
            self._data[sym] = {"hwm": current_price, "updated_at": datetime.now(timezone.utc).isoformat()}
        elif current_price > self._data[sym]["hwm"]:
            self._data[sym]["hwm"] = current_price
            self._data[sym]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        return self.get_stop(sym)

    def get_stop(self, symbol: str) -> float:
        sym = symbol.upper()
        hwm = self._data.get(sym, {}).get("hwm", 0)
        return round(hwm * (1 - self.trail_pct), 2)

    def get_hwm(self, symbol: str) -> float:
        return self._data.get(symbol.upper(), {}).get("hwm", 0)

    def clear(self, symbol: str):
        self._data.pop(symbol.upper(), None)
        self._save()
