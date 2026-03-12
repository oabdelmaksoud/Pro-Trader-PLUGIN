"""SnapTrade broker plugin — aggregator for 20+ brokerages."""

from __future__ import annotations
import logging
import os
import uuid

from pro_trader.core.interfaces import BrokerPlugin
from pro_trader.models.position import (
    Order, OrderResult, Position, Portfolio, OrderSide, AccountSummary,
)

logger = logging.getLogger(__name__)


class SnapTradeBrokerPlugin(BrokerPlugin):
    name = "snaptrade"
    version = "1.0.0"
    description = (
        "SnapTrade aggregator — connect Robinhood, Fidelity, "
        "Schwab, Webull, and 20+ more brokerages"
    )
    supported_assets = ["equity", "option", "crypto"]

    def __init__(self):
        self._client = None
        self._user_id = ""
        self._user_secret = ""
        self._account_id = ""

    def configure(self, config: dict) -> None:
        self._user_id = config.get("user_id", "")
        self._account_id = config.get("account_id", "")

    def startup(self) -> None:
        try:
            from snaptrade.client import Snaptrade
        except ImportError:
            logger.info(
                "snaptrade SDK not installed "
                "(pip install snaptrade-python-sdk)"
            )
            self.enabled = False
            return

        client_id = os.environ.get("SNAPTRADE_CLIENT_ID", "")
        consumer_key = os.environ.get("SNAPTRADE_CONSUMER_KEY", "")
        if not client_id or not consumer_key:
            logger.warning("SnapTrade credentials not set — disabling")
            self.enabled = False
            return

        try:
            self._client = Snaptrade(
                consumer_key=consumer_key,
                client_id=client_id,
            )
            # Use configured user_id or generate one
            if not self._user_id:
                self._user_id = f"protrader-{uuid.uuid4().hex[:8]}"

            # Try to get existing accounts
            try:
                accounts = self._client.account_information.get_all_user_holdings(
                    user_id=self._user_id,
                    user_secret=self._user_secret,
                )
                if accounts and not self._account_id:
                    first = accounts[0] if isinstance(accounts, list) else None
                    if first and hasattr(first, "account"):
                        self._account_id = str(
                            getattr(first.account, "id", "")
                        )
            except Exception:
                # User may not have connected a brokerage yet
                logger.info(
                    "SnapTrade: No accounts linked yet. "
                    "Use 'pro-trader broker add' to connect a brokerage."
                )

        except Exception as e:
            logger.warning(f"SnapTrade init failed: {e}")
            self.enabled = False

    def get_connect_url(self) -> str | None:
        """Generate a SnapTrade redirect URL for the user to connect a brokerage."""
        if not self._client:
            return None
        try:
            response = self._client.authentication.login_snap_trade_user(
                user_id=self._user_id,
                user_secret=self._user_secret,
            )
            return getattr(response, "redirect_uri", None)
        except Exception as e:
            logger.warning(f"SnapTrade connect URL failed: {e}")
            return None

    def register_user(self) -> bool:
        """Register a new SnapTrade user (one-time)."""
        if not self._client:
            return False
        try:
            response = self._client.authentication.register_snap_trade_user(
                user_id=self._user_id,
            )
            self._user_secret = getattr(response, "user_secret", "")
            return bool(self._user_secret)
        except Exception as e:
            logger.warning(f"SnapTrade user registration failed: {e}")
            return False

    def submit_order(self, order: Order) -> OrderResult:
        if not self._client or not self._account_id:
            return OrderResult(
                success=False, status="error",
                message="SnapTrade not connected or no account linked",
            )
        try:
            action = (
                "BUY" if order.side == OrderSide.BUY else "SELL"
            )
            response = self._client.trading.place_force_order(
                user_id=self._user_id,
                user_secret=self._user_secret,
                account_id=self._account_id,
                action=action,
                universal_symbol_id=order.symbol,
                order_type="Market",
                time_in_force="Day",
                units=int(order.qty),
            )
            return OrderResult(
                success=True,
                order_id=str(getattr(response, "order_id", "")),
                status="submitted",
                raw={"response": str(response)},
            )
        except Exception as e:
            return OrderResult(
                success=False, status="error", message=str(e),
            )

    def get_positions(self) -> list[Position]:
        if not self._client or not self._account_id:
            return []
        try:
            holdings = self._client.account_information.get_user_holdings(
                user_id=self._user_id,
                user_secret=self._user_secret,
                account_id=self._account_id,
            )
            positions = []
            for h in getattr(holdings, "positions", []):
                symbol_obj = getattr(h, "symbol", None)
                ticker = (
                    getattr(symbol_obj, "symbol", "")
                    if symbol_obj else ""
                )
                qty = float(getattr(h, "units", 0))
                price = float(getattr(h, "price", 0))
                avg = float(getattr(h, "average_purchase_price", 0))
                positions.append(Position(
                    symbol=ticker,
                    qty=qty,
                    avg_entry=avg,
                    current_price=price,
                    market_value=qty * price,
                    unrealized_pnl=(price - avg) * qty if avg else 0,
                    side="long" if qty > 0 else "short",
                ))
            return positions
        except Exception as e:
            logger.warning(f"Failed to get SnapTrade positions: {e}")
            return []

    def get_portfolio(self) -> Portfolio:
        if not self._client or not self._account_id:
            return Portfolio()
        try:
            holdings = self._client.account_information.get_user_holdings(
                user_id=self._user_id,
                user_secret=self._user_secret,
                account_id=self._account_id,
            )
            positions = self.get_positions()
            total_value = sum(p.market_value for p in positions)
            cash = float(
                getattr(
                    getattr(holdings, "total_value", None),
                    "cash", 0,
                )
            ) if holdings else 0
            return Portfolio(
                positions=positions,
                cash=cash,
                equity=cash + total_value,
            )
        except Exception as e:
            logger.warning(f"Failed to get SnapTrade portfolio: {e}")
            return Portfolio()

    def get_account_summary(self) -> AccountSummary:
        if not self._client or not self._account_id:
            return AccountSummary(broker_name="snaptrade")
        try:
            holdings = self._client.account_information.get_user_holdings(
                user_id=self._user_id,
                user_secret=self._user_secret,
                account_id=self._account_id,
            )
            positions = self.get_positions()
            total_value = sum(p.market_value for p in positions)
            cash = float(
                getattr(
                    getattr(holdings, "total_value", None),
                    "cash", 0,
                )
            ) if holdings else 0
            return AccountSummary(
                broker_name="snaptrade",
                account_id=self._account_id,
                status="active",
                equity=cash + total_value,
                cash=cash,
                open_positions=len(positions),
                position_symbols=[p.symbol for p in positions],
                supported_assets=self.supported_assets,
            )
        except Exception as e:
            logger.warning(
                f"Failed to get SnapTrade account summary: {e}"
            )
            return AccountSummary(broker_name="snaptrade")

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if self._client else "disconnected",
            "account": self._account_id or None,
            "user_id": self._user_id or None,
        }
