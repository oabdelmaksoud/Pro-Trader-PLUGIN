"""
CooperCorp PRJ-002 — Kelly Criterion Position Sizing
Calculates optimal position size using win rate, avg win/loss, and VIX adjustment.
"""
from typing import Optional


def kelly_fraction(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """
    Half-Kelly formula. Returns fraction of portfolio to risk.
    f* = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
    Returns half-Kelly, clamped to [0.01, 0.10].
    """
    try:
        if avg_win_pct <= 0:
            return 0.02
        full_kelly = (win_rate * avg_win_pct - (1 - win_rate) * avg_loss_pct) / avg_win_pct
        half_kelly = full_kelly * 0.5
        return max(0.01, min(0.10, half_kelly))
    except Exception:
        return 0.02


def _vix_multiplier(vix: float) -> float:
    """VIX-adjusted sizing multiplier."""
    if vix < 20:
        return 1.0
    elif vix < 30:
        return 0.7
    else:
        return 0.4


def get_kelly_size(
    ticker: str,
    portfolio_value: float,
    win_rate: Optional[float] = None,
    avg_win: float = 0.08,
    avg_loss: float = 0.03,
    vix: float = 20.0,
    current_price: float = 0.0
) -> dict:
    """
    Calculate Kelly-optimal position size for a stock trade.
    Returns {fraction, dollar_amount, shares, method}
    """
    try:
        # Try to get actual win rate from DB
        method = "default"
        if win_rate is None:
            try:
                from tradingagents.db.signal_db import get_ticker_stats
                stats = get_ticker_stats(ticker)
                if stats and stats.get("total_signals", 0) >= 5:
                    win_rate = stats.get("win_rate", 0.60)
                    avg_pnl = stats.get("avg_pnl", 0)
                    method = "db_historical"
                else:
                    win_rate = 0.60
            except Exception:
                win_rate = 0.60

        fraction = kelly_fraction(win_rate, avg_win, avg_loss)
        vix_mult = _vix_multiplier(vix)
        adjusted_fraction = fraction * vix_mult

        dollar_amount = portfolio_value * adjusted_fraction
        # Hard cap at $25,000 per position
        dollar_amount = min(dollar_amount, 25_000)

        shares = int(dollar_amount / current_price) if current_price > 0 else 0

        return {
            "fraction": round(adjusted_fraction, 4),
            "dollar_amount": round(dollar_amount, 2),
            "shares": shares,
            "win_rate_used": round(win_rate, 3),
            "vix_mult": vix_mult,
            "method": method
        }
    except Exception as e:
        # Safe fallback
        fallback = portfolio_value * 0.02
        return {
            "fraction": 0.02,
            "dollar_amount": fallback,
            "shares": int(fallback / current_price) if current_price > 0 else 0,
            "win_rate_used": 0.60,
            "vix_mult": _vix_multiplier(vix),
            "method": f"fallback_error: {e}"
        }


def get_options_kelly(portfolio_value: float, option_cost_per_contract: float,
                      win_rate: float = 0.60) -> int:
    """
    Max contracts for options position (2% portfolio max, min 1).
    """
    try:
        max_dollar = portfolio_value * 0.02
        contracts = int(max_dollar / (option_cost_per_contract * 100))
        return max(1, min(contracts, 5))  # hard cap at 5 contracts
    except Exception:
        return 1
