"""Realtime data plugin — wraps tradingagents/dataflows/realtime_quotes.py.

Priority chain (first successful wins):
  1. Alpaca REST  — real-time IEX (free with API key)
  2. Finnhub      — real-time (free tier)
  3. Polygon      — 15-min delayed (free tier)
  4. Webull       — real-time (no auth)
  5. yfinance     — last resort (delayed)

This plugin should be preferred over the standalone YFinancePlugin for quotes,
since it tries multiple real-time sources before falling back to yfinance.
"""

from __future__ import annotations
import logging
import sys
from pathlib import Path
from typing import Optional

from pro_trader.core.interfaces import DataPlugin
from pro_trader.models.market_data import Quote

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO))


class RealtimePlugin(DataPlugin):
    name = "realtime"
    version = "1.0.0"
    description = "Real-time quotes via Alpaca/Finnhub/Polygon/Webull (yfinance fallback)"
    provides = ["quotes"]

    def __init__(self):
        self._mod = None

    def startup(self) -> None:
        try:
            from tradingagents.dataflows import realtime_quotes
            self._mod = realtime_quotes
        except ImportError as e:
            logger.warning(f"realtime_quotes not available: {e}")
            self.enabled = False

    def supports(self, symbol: str) -> bool:
        # Supports equities, futures (via proxy map), and crypto
        return True

    def get_quote(self, symbol: str) -> Optional[Quote]:
        if not self._mod:
            return None
        try:
            q = self._mod.get_quote(symbol)
            if not q or not q.get("price"):
                return None

            return Quote(
                symbol=symbol,
                price=q["price"],
                change=q.get("change", 0),
                change_pct=q.get("change_pct", 0),
                volume=q.get("volume", 0),
                high=q.get("high", 0),
                low=q.get("low", 0),
                open=q.get("open", 0),
                prev_close=q.get("prev_close", 0),
                source=q.get("source", "realtime"),
            )
        except Exception as e:
            logger.warning(f"Realtime quote failed for {symbol}: {e}")
            return None

    def get_technicals(self, symbol: str, period: str = "3mo"):
        # Technicals still come from yfinance (historical data needed)
        return None

    def get_fundamentals(self, symbol: str) -> dict:
        return {}

    def get_news(self, symbol: str, limit: int = 10) -> list[dict]:
        return []

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if self._mod else "unavailable",
            "priority_chain": [
                "alpaca (real-time)",
                "finnhub (real-time)",
                "polygon (15-min delay)",
                "webull (real-time)",
                "yfinance (delayed)",
            ],
        }
