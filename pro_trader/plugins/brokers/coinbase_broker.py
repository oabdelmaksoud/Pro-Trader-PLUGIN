"""Coinbase broker plugin — stub for crypto trading."""

from __future__ import annotations
import logging
import os

from pro_trader.core.interfaces import BrokerPlugin
from pro_trader.models.position import (
    Order, OrderResult, Position, Portfolio, AccountSummary,
)

logger = logging.getLogger(__name__)


class CoinbaseBrokerPlugin(BrokerPlugin):
    name = "coinbase"
    version = "0.1.0"
    description = "Coinbase broker (stub — crypto trading pending)"
    supported_assets = ["crypto"]

    def startup(self) -> None:
        api_key = os.environ.get("COINBASE_API_KEY", "")
        if not api_key:
            self.enabled = False
            return
        logger.info("Coinbase plugin loaded (stub mode)")

    def submit_order(self, order: Order) -> OrderResult:
        return OrderResult(
            success=False, status="error",
            message="Coinbase: not yet implemented",
        )

    def get_positions(self) -> list[Position]:
        return []

    def get_portfolio(self) -> Portfolio:
        return Portfolio()

    def get_account_summary(self) -> AccountSummary:
        return AccountSummary(
            broker_name="coinbase", supported_assets=self.supported_assets,
        )

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "stub",
        }
