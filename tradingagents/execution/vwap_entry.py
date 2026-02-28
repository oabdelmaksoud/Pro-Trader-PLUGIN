"""
CooperCorp PRJ-002 — VWAP Entry Logic + Limit Orders
Checks whether current price is positioned well relative to VWAP for entry.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, time as dtime

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def get_vwap(ticker: str) -> float:
    """
    Calculate VWAP from today's 1-minute bars.
    Returns VWAP price or 0.0 on failure.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
        import os
        import alpaca_trade_api as tradeapi
        api = tradeapi.REST(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY"),
            os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        )
        from datetime import date
        bars = api.get_bars(ticker, "1Min", start=date.today().isoformat(), limit=390).df
        if bars.empty:
            raise ValueError("No bars")
        typical = (bars["high"] + bars["low"] + bars["close"]) / 3
        vwap = (typical * bars["volume"]).sum() / bars["volume"].sum()
        return float(vwap)
    except Exception:
        pass

    # Fallback: yfinance 1m
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period="1d", interval="1m")
        if df.empty:
            return 0.0
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vwap = (typical * df["Volume"]).sum() / df["Volume"].sum()
        return float(vwap)
    except Exception:
        return 0.0


def should_enter_now(ticker: str, current_price: float, signal_score: float = 7.0) -> tuple:
    """
    VWAP-based entry check (advisory — not a hard blocker).
    Returns: (should_enter: bool, reason: str, suggested_limit: float)
    """
    try:
        # Check first 5 minutes of market
        now_et = datetime.now()
        market_open = dtime(9, 30)
        now_time = now_et.time()
        if dtime(9, 30) <= now_time <= dtime(9, 35):
            return False, "first_5min", current_price * 0.9995

        vwap = get_vwap(ticker)
        if vwap <= 0:
            return True, "vwap_unavailable", current_price * 0.9995

        deviation = (current_price - vwap) / vwap

        if deviation > 0.02:
            # Price >2% above VWAP — extended, suggest limit near VWAP
            return False, f"extended_above_vwap ({deviation:+.1%})", vwap * 1.005
        elif deviation < -0.02:
            # Price >2% below VWAP — potential breakdown, cautious
            return True, f"below_vwap ({deviation:+.1%}) — momentum caution", current_price * 1.001
        else:
            # Price within 2% of VWAP — ideal entry zone
            return True, f"near_vwap ({deviation:+.1%}) — good zone", current_price * 0.9995

    except Exception as e:
        return True, f"vwap_check_error: {e}", current_price * 0.9995


def get_limit_price(ticker: str, side: str = "buy") -> float:
    """Get a limit price at bid+0.05% (buy) or ask-0.05% (sell)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
        import os
        import alpaca_trade_api as tradeapi
        api = tradeapi.REST(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY"),
            os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        )
        quote = api.get_latest_quote(ticker)
        if side == "buy":
            price = float(quote.bp) * 1.0005
        else:
            price = float(quote.ap) * 0.9995
        return round(price, 2)
    except Exception:
        try:
            import yfinance as yf
            price = yf.Ticker(ticker).fast_info.get("lastPrice", 0)
            adj = 1.0005 if side == "buy" else 0.9995
            return round(float(price) * adj, 2)
        except Exception:
            return 0.0
