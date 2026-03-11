"""Charles Schwab broker plugin — stub (OAuth 2.0 flow deferred)."""

from __future__ import annotations
import logging
import os

from pro_trader.core.interfaces import BrokerPlugin
from pro_trader.models.position import (
    Order, OrderResult, Position, Portfolio, AccountSummary,
)

logger = logging.getLogger(__name__)


class SchwabBrokerPlugin(BrokerPlugin):
    name = "schwab"
    version = "0.1.0"
    description = "Charles Schwab broker (stub — OAuth implementation pending)"
    supported_assets = ["equity", "option", "future"]

    def startup(self) -> None:
        app_key = os.environ.get("SCHWAB_APP_KEY", "")
        if not app_key:
            self.enabled = False
            return
        logger.info("Schwab plugin loaded (stub mode)")

    def submit_order(self, order: Order) -> OrderResult:
        return OrderResult(
            success=False, status="error",
            message="Schwab: not yet implemented",
        )

    def get_positions(self) -> list[Position]:
        return []

    def get_portfolio(self) -> Portfolio:
        return Portfolio()

    def get_account_summary(self) -> AccountSummary:
        return AccountSummary(
            broker_name="schwab", supported_assets=self.supported_assets,
        )

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "stub",
        }
