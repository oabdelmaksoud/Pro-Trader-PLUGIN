"""Tradier broker plugin — REST API for stocks and options."""

from __future__ import annotations
import logging
import os

from pro_trader.core.interfaces import BrokerPlugin
from pro_trader.models.position import (
    Order, OrderResult, Position, Portfolio, AccountSummary,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.tradier.com/v1"
_SANDBOX_URL = "https://sandbox.tradier.com/v1"


class TradierBrokerPlugin(BrokerPlugin):
    name = "tradier"
    version = "0.1.0"
    description = "Tradier broker (account sync works, orders pending)"
    supported_assets = ["equity", "option"]

    def __init__(self):
        self._token = ""
        self._account_id = ""
        self._sandbox = False

    def configure(self, config: dict) -> None:
        self._sandbox = config.get("sandbox", False)

    def startup(self) -> None:
        self._token = os.environ.get("TRADIER_ACCESS_TOKEN", "")
        self._account_id = os.environ.get("TRADIER_ACCOUNT_ID", "")
        if not self._token:
            logger.info("Tradier access token not set — disabling")
            self.enabled = False

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make authenticated request to Tradier API."""
        import requests
        base = _SANDBOX_URL if self._sandbox else _BASE_URL
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        resp = requests.request(
            method, f"{base}{path}", headers=headers, timeout=15, **kwargs,
        )
        resp.raise_for_status()
        return resp.json()

    def submit_order(self, order: Order) -> OrderResult:
        return OrderResult(
            success=False, status="error",
            message="Tradier order submission not yet implemented",
        )

    def get_positions(self) -> list[Position]:
        if not self._token or not self._account_id:
            return []
        try:
            data = self._request(
                "GET", f"/accounts/{self._account_id}/positions",
            )
            pos_data = data.get("positions", {}).get("position", [])
            if isinstance(pos_data, dict):
                pos_data = [pos_data]
            return [
                Position(
                    symbol=p.get("symbol", ""),
                    qty=float(p.get("quantity", 0)),
                    avg_entry=float(p.get("cost_basis", 0))
                    / max(float(p.get("quantity", 1)), 1),
                    current_price=float(p.get("last", 0)),
                    market_value=float(
                        p.get("quantity", 0)
                    ) * float(p.get("last", 0)),
                    side="long" if float(
                        p.get("quantity", 0)
                    ) > 0 else "short",
                )
                for p in pos_data
            ]
        except Exception as e:
            logger.warning(f"Failed to get Tradier positions: {e}")
            return []

    def get_portfolio(self) -> Portfolio:
        if not self._token or not self._account_id:
            return Portfolio()
        try:
            data = self._request(
                "GET", f"/accounts/{self._account_id}/balances",
            )
            bal = data.get("balances", {})
            positions = self.get_positions()
            return Portfolio(
                positions=positions,
                cash=float(bal.get("cash", {}).get("cash_available", 0)),
                equity=float(bal.get("total_equity", 0)),
                buying_power=float(
                    bal.get("margin", {}).get("stock_buying_power", 0)
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to get Tradier portfolio: {e}")
            return Portfolio()

    def get_account_summary(self) -> AccountSummary:
        if not self._token or not self._account_id:
            return AccountSummary(broker_name="tradier")
        try:
            data = self._request(
                "GET", f"/accounts/{self._account_id}/balances",
            )
            bal = data.get("balances", {})
            positions = self.get_positions()
            return AccountSummary(
                broker_name="tradier",
                account_id=self._account_id,
                status=bal.get("account_type", "active"),
                equity=float(bal.get("total_equity", 0)),
                cash=float(
                    bal.get("cash", {}).get("cash_available", 0)
                ),
                buying_power=float(
                    bal.get("margin", {}).get("stock_buying_power", 0)
                ),
                pattern_day_trader=bal.get(
                    "pdt", {}).get("pdt_status", False
                ),
                open_positions=len(positions),
                position_symbols=[p.symbol for p in positions],
                supported_assets=self.supported_assets,
            )
        except Exception as e:
            logger.warning(
                f"Failed to get Tradier account summary: {e}"
            )
            return AccountSummary(broker_name="tradier")

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if self._token else "disconnected",
        }
