"""Alpaca broker plugin — wraps tradingagents/brokers/alpaca.py."""

from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

from pro_trader.core.interfaces import BrokerPlugin
from pro_trader.models.position import (
    Order, OrderResult, Position, Portfolio, OrderSide, AccountSummary,
)

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO))


class AlpacaBrokerPlugin(BrokerPlugin):
    name = "alpaca"
    version = "1.1.0"
    description = "Alpaca paper/live trading broker"
    supported_assets = ["equity", "option", "crypto"]

    def __init__(self):
        self._paper = True
        self._client = None

    def configure(self, config: dict) -> None:
        self._paper = config.get("paper", True)

    def startup(self) -> None:
        try:
            from tradingagents.brokers.alpaca import AlpacaBroker
            self._client = AlpacaBroker()
        except Exception as e:
            logger.warning(f"Alpaca broker init failed: {e}")
            self.enabled = False

    def submit_order(self, order: Order) -> OrderResult:
        if not self._client:
            return OrderResult(success=False, status="error", message="Broker not initialized")

        try:
            side = "buy" if order.side == OrderSide.BUY else "sell"
            result = self._client.place_order(
                symbol=order.symbol,
                side=side,
                qty=order.qty,
                order_type=order.order_type.value,
                stop_loss=order.stop_price,
                take_profit=order.take_profit,
            )
            return OrderResult(
                success=True,
                order_id=str(result.get("id", "")),
                status=result.get("status", "submitted"),
                raw=result,
            )
        except Exception as e:
            return OrderResult(success=False, status="error", message=str(e))

    def get_positions(self) -> list:
        if not self._client:
            return []
        try:
            positions = self._client.get_positions()
            return [
                Position(
                    symbol=p.get("symbol", ""),
                    qty=float(p.get("qty", 0)),
                    avg_entry=float(p.get("avg_entry_price", 0)),
                    current_price=float(p.get("current_price", 0)),
                    unrealized_pnl=float(p.get("unrealized_pl", 0)),
                    market_value=float(p.get("market_value", 0)),
                    side="long" if float(p.get("qty", 0)) > 0 else "short",
                )
                for p in (positions if isinstance(positions, list) else [])
            ]
        except Exception as e:
            logger.warning(f"Failed to get positions: {e}")
            return []

    def get_portfolio(self) -> Portfolio:
        if not self._client:
            return Portfolio()
        try:
            account = self._client.get_account()
            positions = self.get_positions()
            return Portfolio(
                positions=positions,
                cash=float(account.get("cash", 0)),
                equity=float(account.get("equity", 0)),
                buying_power=float(account.get("buying_power", 0)),
                today_pnl=float(account.get("daily_pnl", 0)),
            )
        except Exception as e:
            logger.warning(f"Failed to get portfolio: {e}")
            return Portfolio()

    def get_account_summary(self) -> AccountSummary:
        if not self._client:
            return AccountSummary(broker_name="alpaca")
        try:
            account = self._client.get_account()
            positions = self.get_positions()
            return AccountSummary(
                broker_name="alpaca",
                account_id=str(account.get("id", "")),
                status=str(account.get("status", "")),
                equity=float(account.get("equity", 0)),
                cash=float(account.get("cash", 0)),
                buying_power=float(account.get("buying_power", 0)),
                today_pnl=float(account.get("daily_pnl", 0)),
                day_trade_count=int(account.get("daytrade_count", 0)),
                pattern_day_trader=bool(account.get("pattern_day_trader", False)),
                open_positions=len(positions),
                position_symbols=[p.symbol for p in positions],
                supported_assets=self.supported_assets,
                raw=account if isinstance(account, dict) else {},
            )
        except Exception as e:
            logger.warning(f"Failed to get account summary: {e}")
            return AccountSummary(broker_name="alpaca")

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if self._client else "disconnected",
            "paper": self._paper,
        }
