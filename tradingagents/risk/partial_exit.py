"""
Partial exit manager: take 50% off at +5%, let rest ride to +8% stop or trailing stop.
"""
import json
from pathlib import Path

PARTIAL_EXITS_FILE = Path(__file__).parent.parent.parent / "logs" / "partial_exits.json"


class PartialExitManager:
    def __init__(self):
        self._data = self._load()

    def _load(self):
        if PARTIAL_EXITS_FILE.exists():
            try:
                return json.loads(PARTIAL_EXITS_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        PARTIAL_EXITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PARTIAL_EXITS_FILE.write_text(json.dumps(self._data, indent=2))

    def has_taken_partial(self, symbol: str) -> bool:
        return self._data.get(symbol.upper(), {}).get("partial_taken", False)

    def mark_partial_taken(self, symbol: str, price: float, qty_closed: float):
        self._data[symbol.upper()] = {
            "partial_taken": True,
            "partial_price": price,
            "qty_closed": qty_closed,
        }
        self._save()

    def clear(self, symbol: str):
        self._data.pop(symbol.upper(), None)
        self._save()
