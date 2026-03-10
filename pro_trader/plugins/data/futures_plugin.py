"""Futures data plugin — wraps tradingagents/dataflows/futures_data.py."""

from __future__ import annotations
import logging
import sys
from pathlib import Path
from typing import Optional

from pro_trader.core.interfaces import DataPlugin
from pro_trader.models.market_data import MarketData, Quote, Technicals

logger = logging.getLogger(__name__)

# Ensure legacy module is importable
_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO))


class FuturesPlugin(DataPlugin):
    name = "futures"
    version = "1.0.0"
    description = "CME Micro Futures data (contract specs, quotes via proxy)"
    provides = ["quotes", "technicals"]

    def __init__(self):
        self._futures_mod = None
        self._account_value = 500
        self._margin_buffer = 1.5

    def configure(self, config: dict) -> None:
        self._account_value = config.get("account_value", 500)
        self._margin_buffer = config.get("margin_buffer", 1.5)

    def startup(self) -> None:
        try:
            from tradingagents.dataflows import futures_data
            self._futures_mod = futures_data
        except ImportError:
            logger.warning("futures_data module not found — plugin disabled")
            self.enabled = False

    def supports(self, symbol: str) -> bool:
        """Only handle futures symbols (start with / or match known roots)."""
        if not self._futures_mod:
            return False
        return self._futures_mod.is_futures_symbol(symbol)

    def get_quote(self, symbol: str) -> Optional[Quote]:
        if not self._futures_mod:
            return None
        try:
            raw = self._futures_mod.get_futures_quote(symbol)
            if "error" in raw:
                logger.warning(f"Futures quote error for {symbol}: {raw['error']}")
                return None
            return Quote(
                symbol=symbol,
                price=raw.get("price", 0),
                change=raw.get("change", 0),
                change_pct=raw.get("change_pct", 0),
                volume=raw.get("volume", 0),
                high=raw.get("high", 0),
                low=raw.get("low", 0),
                open=raw.get("open", 0),
                source="futures_proxy",
            )
        except Exception as e:
            logger.warning(f"Futures quote failed for {symbol}: {e}")
            return None

    def get_technicals(self, symbol: str, period: str = "3mo") -> Optional[Technicals]:
        if not self._futures_mod:
            return None
        try:
            raw = self._futures_mod.get_futures_technicals(symbol)
            if "error" in raw:
                return None
            return Technicals(
                symbol=symbol,
                rsi=raw.get("rsi"),
                above_sma20=raw.get("above_sma20", False),
                above_sma50=raw.get("above_sma50", False),
                volume_ratio=raw.get("volume_ratio", 1.0),
                macd_cross=raw.get("macd_cross"),
                bb_squeeze=raw.get("bb_squeeze", False),
                bb_position=raw.get("bb_position"),
                source="futures_proxy",
            )
        except Exception as e:
            logger.warning(f"Futures technicals failed for {symbol}: {e}")
            return None

    def get_market_data(self, symbol: str, full: bool = False) -> MarketData:
        """Override to include futures-specific fields."""
        data = super().get_market_data(symbol, full)
        data.asset_type = "futures"

        if self._futures_mod:
            spec = self._futures_mod.get_contract_spec(symbol)
            if spec:
                data.contract_spec = spec
            ctx = self._futures_mod.format_futures_context(symbol)
            if ctx:
                data.futures_context = ctx

        return data

    def get_affordable_contracts(self, account_value: float | None = None) -> list[dict]:
        """Get contracts affordable at current account value."""
        if not self._futures_mod:
            return []
        val = account_value or self._account_value
        return self._futures_mod.get_affordable_contracts(val, self._margin_buffer)

    def health_check(self) -> dict:
        avail = self._futures_mod is not None
        contracts = len(self._futures_mod.MICRO_FUTURES) if avail else 0
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if avail else "unavailable",
            "contracts_registered": contracts,
        }
