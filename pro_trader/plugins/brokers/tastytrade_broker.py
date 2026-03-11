"""Tastytrade broker plugin — stocks, options, futures, crypto."""

from __future__ import annotations
import logging
import os

from pro_trader.core.interfaces import BrokerPlugin
from pro_trader.models.position import (
    Order, OrderResult, Position, Portfolio, OrderSide, AccountSummary,
)

logger = logging.getLogger(__name__)


class TastytradeBrokerPlugin(BrokerPlugin):
    name = "tastytrade"
    version = "1.0.0"
    description = "Tastytrade broker — options, futures, stocks, crypto"
    supported_assets = ["equity", "option", "future", "crypto"]

    def __init__(self):
        self._session = None
        self._account = None
        self._account_id = ""

    def configure(self, config: dict) -> None:
        self._account_id = config.get("account_id", "")

    def startup(self) -> None:
        try:
            from tastytrade import Session, Account  # noqa: F811
            username = os.environ.get("TASTYTRADE_USERNAME", "")
            password = os.environ.get("TASTYTRADE_PASSWORD", "")
            if not username or not password:
                logger.warning("Tastytrade credentials not set — disabling")
                self.enabled = False
                return
            self._session = Session(username, password)
            accounts = Account.get_accounts(self._session)
            if self._account_id:
                self._account = next(
                    (a for a in accounts
                     if a.account_number == self._account_id), None
                )
            else:
                self._account = accounts[0] if accounts else None
            if not self._account:
                logger.warning("No Tastytrade account found — disabling")
                self.enabled = False
        except ImportError:
            logger.info("tastytrade SDK not installed (pip install tastytrade)")
            self.enabled = False
        except Exception as e:
            logger.warning(f"Tastytrade init failed: {e}")
            self.enabled = False

    def _ensure_session(self) -> bool:
        """Re-authenticate if session expired."""
        if self._session and self._account:
            return True
        try:
            from tastytrade import Session, Account
            username = os.environ.get("TASTYTRADE_USERNAME", "")
            password = os.environ.get("TASTYTRADE_PASSWORD", "")
            if not username or not password:
                return False
            self._session = Session(username, password)
            accounts = Account.get_accounts(self._session)
            self._account = accounts[0] if accounts else None
            return self._account is not None
        except Exception as e:
            logger.warning(f"Tastytrade re-auth failed: {e}")
            return False

    def submit_order(self, order: Order) -> OrderResult:
        if not self._ensure_session():
            return OrderResult(
                success=False, status="error", message="Not connected",
            )
        try:
            from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce
            from tastytrade.instruments import Equity

            symbol = Equity.get_equity(self._session, order.symbol)
            action = (OrderAction.BUY_TO_OPEN
                      if order.side == OrderSide.BUY
                      else OrderAction.SELL_TO_CLOSE)

            leg = symbol.build_leg(int(order.qty), action)
            new_order = NewOrder(
                time_in_force=OrderTimeInForce.DAY,
                order_type="Market",
                legs=[leg],
            )
            response = self._account.place_order(
                self._session, new_order, dry_run=False,
            )
            return OrderResult(
                success=True,
                order_id=str(getattr(response, "id", "")),
                status="submitted",
                raw={"response": str(response)},
            )
        except Exception as e:
            return OrderResult(
                success=False, status="error", message=str(e),
            )

    def get_positions(self) -> list[Position]:
        if not self._ensure_session():
            return []
        try:
            positions = self._account.get_positions(self._session)
            return [
                Position(
                    symbol=str(getattr(p, "symbol", "")),
                    qty=float(getattr(p, "quantity", 0)),
                    avg_entry=float(getattr(p, "average_open_price", 0)),
                    current_price=float(getattr(p, "close_price", 0)),
                    unrealized_pnl=float(
                        getattr(p, "realized_day_gain", 0)
                    ),
                    market_value=float(getattr(p, "market_value", 0)),
                    side="long" if float(
                        getattr(p, "quantity", 0)
                    ) > 0 else "short",
                    asset_type=str(
                        getattr(p, "instrument_type", "equity")
                    ).lower(),
                )
                for p in positions
            ]
        except Exception as e:
            logger.warning(f"Failed to get Tastytrade positions: {e}")
            return []

    def get_portfolio(self) -> Portfolio:
        if not self._ensure_session():
            return Portfolio()
        try:
            balances = self._account.get_balances(self._session)
            positions = self.get_positions()
            return Portfolio(
                positions=positions,
                cash=float(getattr(balances, "cash_balance", 0)),
                equity=float(
                    getattr(balances, "net_liquidating_value", 0)
                ),
                buying_power=float(
                    getattr(balances, "equity_buying_power", 0)
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to get Tastytrade portfolio: {e}")
            return Portfolio()

    def get_account_summary(self) -> AccountSummary:
        if not self._ensure_session():
            return AccountSummary(broker_name="tastytrade")
        try:
            balances = self._account.get_balances(self._session)
            positions = self.get_positions()
            return AccountSummary(
                broker_name="tastytrade",
                account_id=str(
                    getattr(self._account, "account_number", "")
                ),
                status="active",
                equity=float(
                    getattr(balances, "net_liquidating_value", 0)
                ),
                cash=float(getattr(balances, "cash_balance", 0)),
                buying_power=float(
                    getattr(balances, "equity_buying_power", 0)
                ),
                open_positions=len(positions),
                position_symbols=[p.symbol for p in positions],
                supported_assets=self.supported_assets,
            )
        except Exception as e:
            logger.warning(f"Failed to get Tastytrade account summary: {e}")
            return AccountSummary(broker_name="tastytrade")

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if self._session else "disconnected",
            "account": (
                self._account.account_number if self._account else None
            ),
        }
