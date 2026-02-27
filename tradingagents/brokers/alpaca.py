"""
CooperCorp PRJ-002 — Alpaca Broker Integration
Paper trading: https://paper-api.alpaca.markets
Live trading:  https://api.alpaca.markets
"""
import os
import alpaca_trade_api as tradeapi
from typing import Optional


class AlpacaBroker:
    """
    Alpaca Markets broker adapter.
    Replaces the simulated exchange in agents/managers/portfolio_manager.py
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api = tradeapi.REST(
            api_key or os.environ["ALPACA_API_KEY"],
            secret_key or os.environ["ALPACA_SECRET_KEY"],
            base_url or os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )

    # ── Account ──────────────────────────────────────────────────────────────

    def get_account(self):
        return self.api.get_account()

    def get_portfolio_value(self) -> float:
        return float(self.api.get_account().portfolio_value)

    def get_buying_power(self) -> float:
        return float(self.api.get_account().buying_power)

    def get_cash(self) -> float:
        return float(self.api.get_account().cash)

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self):
        return self.api.list_positions()

    def get_position(self, symbol: str):
        try:
            return self.api.get_position(symbol)
        except Exception:
            return None

    # ── Orders ────────────────────────────────────────────────────────────────

    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,  # "buy" | "sell"
        order_type: str = "market",
        time_in_force: str = "day",
    ):
        return self.api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type=order_type,
            time_in_force=time_in_force,
        )

    def cancel_all_orders(self):
        return self.api.cancel_all_orders()

    def list_orders(self, status: str = "open"):
        return self.api.list_orders(status=status)

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_latest_bar(self, symbol: str):
        bars = self.api.get_bars(symbol, "1Min", limit=1).df
        return bars.iloc[-1] if not bars.empty else None

    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 30):
        return self.api.get_bars(symbol, timeframe, limit=limit).df

    # ── Convenience ───────────────────────────────────────────────────────────

    def status_summary(self) -> dict:
        acct = self.api.get_account()
        return {
            "account_id": acct.id,
            "status": acct.status,
            "portfolio_value": float(acct.portfolio_value),
            "buying_power": float(acct.buying_power),
            "cash": float(acct.cash),
            "positions": len(self.api.list_positions()),
        }


# ── Quick connectivity test ───────────────────────────────────────────────────
if __name__ == "__main__":
    broker = AlpacaBroker()
    summary = broker.status_summary()
    for k, v in summary.items():
        print(f"{k}: {v}")
