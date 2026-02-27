"""
CooperCorp PRJ-002 — Earnings Risk Filter
Detects upcoming earnings to penalize trading scores.
"""
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

EARNINGS_PENALTY = -2.0


class EarningsFilter:
    def earnings_date(self, symbol: str) -> Optional[str]:
        """Return next earnings date as YYYY-MM-DD string, or None."""
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            cal = t.calendar
            if cal is None:
                return None
            # calendar is a dict with 'Earnings Date' key or a DataFrame
            if hasattr(cal, 'columns'):
                # DataFrame format
                if 'Earnings Date' in cal.columns:
                    val = cal['Earnings Date'].iloc[0]
                    return str(val.date()) if hasattr(val, 'date') else str(val)[:10]
            elif isinstance(cal, dict):
                val = cal.get('Earnings Date', [None])
                if isinstance(val, list) and val:
                    val = val[0]
                if val is not None:
                    return str(val)[:10]
            return None
        except Exception as e:
            logger.debug(f"EarningsFilter: could not fetch earnings for {symbol}: {e}")
            return None

    def has_earnings_soon(self, symbol: str, days_ahead: int = 1) -> bool:
        """Returns True if earnings are within days_ahead calendar days."""
        try:
            ed = self.earnings_date(symbol)
            if ed is None:
                return False
            earnings_dt = date.fromisoformat(ed)
            today = date.today()
            delta = (earnings_dt - today).days
            return 0 <= delta <= days_ahead
        except Exception as e:
            logger.debug(f"EarningsFilter: error checking {symbol}: {e}")
            return False

    def score_penalty(self, symbol: str, days_ahead: int = 1) -> float:
        """Returns EARNINGS_PENALTY if earnings soon, else 0.0."""
        if self.has_earnings_soon(symbol, days_ahead):
            logger.info(f"EarningsFilter: {symbol} has earnings within {days_ahead}d — penalty {EARNINGS_PENALTY}")
            return EARNINGS_PENALTY
        return 0.0
