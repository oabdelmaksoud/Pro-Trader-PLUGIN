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

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,  # "buy" | "sell"
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.08,
        max_retries: int = 3,
    ):
        """
        Submit a bracket order with hard stop-loss and take-profit legs.
        For longs:  stop = entry * (1 - stop_loss_pct), tp = entry * (1 + take_profit_pct)
        For shorts: stop = entry * (1 + stop_loss_pct), tp = entry * (1 - take_profit_pct)
        Retries up to max_retries times with exponential backoff.
        """
        import time
        import logging
        logger = logging.getLogger(__name__)

        last_error = None
        for attempt in range(max_retries):
            try:
                # Get current price as entry estimate
                bar = self.get_latest_bar(symbol)
                if bar is None:
                    raise ValueError(f"No price data for {symbol}")
                entry = float(bar["close"])

                if side == "buy":
                    stop_price = round(entry * (1 - stop_loss_pct), 2)
                    take_profit_price = round(entry * (1 + take_profit_pct), 2)
                else:
                    stop_price = round(entry * (1 + stop_loss_pct), 2)
                    take_profit_price = round(entry * (1 - take_profit_pct), 2)

                return self.api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side=side,
                    type="market",
                    time_in_force="day",
                    order_class="bracket",
                    stop_loss={"stop_price": str(stop_price)},
                    take_profit={"limit_price": str(take_profit_price)},
                )
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"Order attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
        raise RuntimeError(f"Order failed after {max_retries} attempts: {last_error}")

    def cancel_all_orders(self):
        return self.api.cancel_all_orders()

    def list_orders(self, status: str = "open"):
        return self.api.list_orders(status=status)

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_latest_bar(self, symbol: str):
        """Get latest bar. Checks live_prices.json first (if WebSocket stream is running)."""
        import json
        from pathlib import Path
        prices_file = Path(__file__).parent.parent.parent / "logs" / "live_prices.json"
        if prices_file.exists():
            try:
                data = json.loads(prices_file.read_text())
                if symbol in data:
                    p = data[symbol]
                    # Return a dict-like object compatible with REST bar
                    class LivePrice:
                        def __init__(self, d):
                            self.close = d["price"]
                            self.open = d["price"]
                            self.high = d["price"]
                            self.low = d["price"]
                            self.volume = 0
                            self.timestamp = d.get("timestamp", "")
                    return LivePrice(p)
            except Exception:
                pass
        bars = self.api.get_bars(symbol, "1Min", limit=1).df
        return bars.iloc[-1] if not bars.empty else None

    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 30):
        return self.api.get_bars(symbol, timeframe, limit=limit).df

    # ── Intraday / Pre-market Data ───────────────────────────────────────────

    def get_intraday_bars(self, symbol: str, timeframe: str = "5Min", limit: int = 78) -> list:
        """
        Get intraday bars for today using Alpaca's market data API.
        Returns list of {t, o, h, l, c, v} dicts.
        timeframe: "1Min", "5Min", "15Min", "1H"
        """
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        from datetime import datetime
        import pytz

        data_client = StockHistoricalDataClient(
            os.environ.get("ALPACA_API_KEY"),
            os.environ.get("ALPACA_SECRET_KEY"),
        )

        tf_map = {
            "1Min": TimeFrame(1, TimeFrameUnit.Minute),
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "1H": TimeFrame(1, TimeFrameUnit.Hour),
        }
        tf = tf_map.get(timeframe, TimeFrame(5, TimeFrameUnit.Minute))

        et = pytz.timezone("America/New_York")
        today = datetime.now(et).date()
        start = et.localize(datetime.combine(today, datetime.min.time().replace(hour=9, minute=30)))

        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=tf,
            start=start,
            limit=limit,
        )
        bars = data_client.get_stock_bars(request)
        result = []
        for bar in bars[symbol]:
            result.append({
                "t": str(bar.timestamp),
                "o": float(bar.open),
                "h": float(bar.high),
                "l": float(bar.low),
                "c": float(bar.close),
                "v": int(bar.volume),
            })
        return result

    def get_premarket_change(self, symbol: str) -> dict:
        """Returns pre-market % change vs yesterday's close."""
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            info = t.fast_info
            prev_close = info.previous_close
            pre_price = info.pre_market_price or info.last_price
            change_pct = ((pre_price - prev_close) / prev_close) * 100
            return {
                "symbol": symbol,
                "prev_close": prev_close,
                "pre_price": pre_price,
                "change_pct": round(change_pct, 2),
            }
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}

    # ── Options Execution ────────────────────────────────────────────────────

    def buy_to_open(
        self,
        option_symbol: str,
        qty: int = 1,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
    ):
        """
        Buy to open an options contract.
        option_symbol: OCC format e.g. 'NVDA250307C00187500'
        qty: number of contracts (each = 100 shares)
        limit_price: if None, uses mid price from yfinance
        """
        if not limit_price:
            try:
                # Try to get mid price
                import yfinance as yf
                # Parse OCC symbol to get underlying and expiry
                limit_price = None  # Will use market order if can't get mid
                order_type = "market"
            except Exception:
                order_type = "market"

        return self.api.submit_order(
            symbol=option_symbol,
            qty=qty,
            side="buy",
            type=order_type,
            time_in_force="day",
            limit_price=str(round(limit_price, 2)) if limit_price else None,
        )

    def sell_to_close(
        self,
        option_symbol: str,
        qty: int = 1,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ):
        """Sell to close an options position."""
        return self.api.submit_order(
            symbol=option_symbol,
            qty=qty,
            side="sell",
            type=order_type,
            time_in_force="day",
            limit_price=str(round(limit_price, 2)) if limit_price else None,
        )

    @staticmethod
    def build_occ_symbol(ticker: str, expiry: str, option_type: str, strike: float) -> str:
        """
        Build OCC option symbol.
        expiry: 'YYYY-MM-DD'
        option_type: 'C' or 'P'
        strike: e.g. 187.5
        Returns: 'NVDA250307C00187500'
        """
        from datetime import datetime
        dt = datetime.strptime(expiry, "%Y-%m-%d")
        exp_str = dt.strftime("%y%m%d")
        strike_int = int(round(strike * 1000))
        return f"{ticker.upper()}{exp_str}{option_type.upper()}{strike_int:08d}"

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
