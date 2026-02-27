"""
CooperCorp PRJ-002 — Trade Tagger
Tags positions as swing/day/options to control EOD close behavior.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
TAG_FILE = Path(__file__).parent.parent.parent / "logs" / "trade_tags.json"


class TradeTagger:
    VALID_TAGS = {"swing", "day", "options"}

    def _load(self) -> dict:
        if TAG_FILE.exists():
            try:
                return json.loads(TAG_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save(self, data: dict):
        TAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        TAG_FILE.write_text(json.dumps(data, indent=2))

    def tag(self, symbol: str, tag: str):
        """Tag symbol as 'swing', 'day', or 'options'."""
        symbol = symbol.upper()
        if tag not in self.VALID_TAGS:
            raise ValueError(f"Invalid tag '{tag}'. Must be one of {self.VALID_TAGS}")
        data = self._load()
        data[symbol] = tag
        self._save(data)
        logger.info(f"Tagged {symbol} as '{tag}'")

    def get_tag(self, symbol: str) -> str:
        """Returns tag for symbol, defaults to 'day'."""
        return self._load().get(symbol.upper(), "day")

    def is_swing(self, symbol: str) -> bool:
        return self.get_tag(symbol) == "swing"

    def clear(self, symbol: str):
        """Remove tag for symbol."""
        data = self._load()
        data.pop(symbol.upper(), None)
        self._save(data)
