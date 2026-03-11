"""Interactive Brokers plugin — requires TWS/Gateway running."""

from __future__ import annotations
import logging
import os

from pro_trader.core.interfaces import BrokerPlugin
from pro_trader.models.position import (
    Order, OrderResult, Position, Portfolio, OrderSide, AccountSummary,
)

logger = logging.getLogger(__name__)


class IBKRBrokerPlugin(BrokerPlugin):
    name = "ibkr"
    version = "1.0.0"
    description = "Interactive Brokers via TWS/Gateway (ib_insync)"
    supported_assets = ["equity", "option", "future", "forex", "crypto"]

    def __init__(self):
        self._ib = None
        self._host = "127.0.0.1"
        self._port = 7497
        self._client_id = 1

    def configure(self, config: dict) -> None:
        self._host = config.get(
            "host", os.environ.get("IBKR_HOST", "127.0.0.1")
        )
        self._port = int(
            config.get("port", os.environ.get("IBKR_PORT", "7497"))
        )
        self._client_id = int(
            config.get("client_id", os.environ.get("IBKR_CLIENT_ID", "1"))
        )

    def startup(self) -> None:
        try:
            from ib_insync import IB
            self._ib = IB()
            self._ib.connect(
                self._host, self._port, clientId=self._client_id
            )
            if not self._ib.isConnected():
                logger.warning(
                    "IBKR: Could not connect to TWS/Gateway — disabling"
                )
                self.enabled = False
        except ImportError:
            logger.info("ib_insync not installed (pip install ib_insync)")
            self.enabled = False
        except Exception as e:
            logger.warning(
                f"IBKR init failed: {e} — Is TWS/Gateway running?"
            )
            self.enabled = False

    def shutdown(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    def submit_order(self, order: Order) -> OrderResult:
        if not self._ib or not self._ib.isConnected():
            return OrderResult(
                success=False, status="error",
                message="Not connected to TWS/Gateway",
            )
        try:
            from ib_insync import Stock, MarketOrder, LimitOrder

            contract = Stock(order.symbol, "SMART", "USD")
            action = "BUY" if order.side == OrderSide.BUY else "SELL"

            if order.limit_price:
                ib_order = LimitOrder(
                    action, int(order.qty), order.limit_price,
                )
            else:
                ib_order = MarketOrder(action, int(order.qty))

            trade = self._ib.placeOrder(contract, ib_order)
            return OrderResult(
                success=True,
                order_id=str(trade.order.orderId),
                status="submitted",
                raw={"trade": str(trade)},
            )
        except Exception as e:
            return OrderResult(
                success=False, status="error", message=str(e),
            )

    def get_positions(self) -> list[Position]:
        if not self._ib or not self._ib.isConnected():
            return []
        try:
            ib_positions = self._ib.positions()
            return [
                Position(
                    symbol=p.contract.symbol,
                    qty=float(p.position),
                    avg_entry=float(p.avgCost),
                    side="long" if p.position > 0 else "short",
                    asset_type=(
                        p.contract.secType.lower()
                        if hasattr(p.contract, "secType") else "equity"
                    ),
                )
                for p in ib_positions
            ]
        except Exception as e:
            logger.warning(f"Failed to get IBKR positions: {e}")
            return []

    def get_portfolio(self) -> Portfolio:
        if not self._ib or not self._ib.isConnected():
            return Portfolio()
        try:
            summary_tags = self._ib.accountSummary()
            vals = {v.tag: float(v.value) for v in summary_tags
                    if v.value.replace(".", "").replace("-", "").isdigit()}
            positions = self.get_positions()
            return Portfolio(
                positions=positions,
                cash=vals.get("TotalCashValue", 0),
                equity=vals.get("NetLiquidation", 0),
                buying_power=vals.get("BuyingPower", 0),
            )
        except Exception as e:
            logger.warning(f"Failed to get IBKR portfolio: {e}")
            return Portfolio()

    def get_account_summary(self) -> AccountSummary:
        if not self._ib or not self._ib.isConnected():
            return AccountSummary(broker_name="ibkr")
        try:
            summary_tags = self._ib.accountSummary()
            vals = {v.tag: v.value for v in summary_tags}
            positions = self.get_positions()

            def fval(key: str) -> float:
                try:
                    return float(vals.get(key, 0))
                except (ValueError, TypeError):
                    return 0.0

            return AccountSummary(
                broker_name="ibkr",
                account_id=str(
                    summary_tags[0].account if summary_tags else ""
                ),
                status="active",
                equity=fval("NetLiquidation"),
                cash=fval("TotalCashValue"),
                buying_power=fval("BuyingPower"),
                today_pnl=fval("UnrealizedPnL"),
                open_positions=len(positions),
                position_symbols=[p.symbol for p in positions],
                supported_assets=self.supported_assets,
                raw=vals,
            )
        except Exception as e:
            logger.warning(f"Failed to get IBKR account summary: {e}")
            return AccountSummary(broker_name="ibkr")

    def health_check(self) -> dict:
        connected = self._ib.isConnected() if self._ib else False
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if connected else "disconnected",
            "tws_required": True,
        }
