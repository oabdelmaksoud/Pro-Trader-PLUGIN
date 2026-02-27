"""
CooperCorp PRJ-002 — IV Percentile / IV Rank Calculator
Avoids buying options when IV is inflated (post-earnings crush risk).

IV Rank = (current IV - 52w low IV) / (52w high IV - 52w low IV) * 100
IV Percentile = % of days in past year where IV was BELOW current IV

Guideline:
  IV Rank < 30 → cheap options → prefer buying options
  IV Rank 30-50 → moderate → acceptable
  IV Rank > 50 → expensive → avoid buying options, consider spreads
  IV Rank > 80 → very expensive → likely pre-earnings, skip or use debit spread
"""
import yfinance as yf
import numpy as np
from typing import Optional


def get_iv_rank(symbol: str, lookback_days: int = 252) -> dict:
    """
    Calculate IV Rank and IV Percentile for a ticker using historical option data.
    Uses ATM implied vol approximation from yfinance (HV proxy when IV not available).
    
    For a free tier approach: uses 30-day historical volatility as HV,
    and current ATM options IV from the chain.
    """
    try:
        sym_map = {"BTC": "BTC-USD"}
        sym = sym_map.get(symbol.upper(), symbol)
        tk = yf.Ticker(sym)

        # Get current ATM IV from nearest expiry
        current_iv = None
        try:
            exps = tk.options
            if exps:
                # Use nearest expiry (most liquid)
                chain = tk.option_chain(exps[0])
                hist_price = tk.fast_info.last_price or tk.fast_info.regular_market_price
                if hist_price:
                    calls = chain.calls.copy()
                    calls["strike_diff"] = abs(calls["strike"] - float(hist_price))
                    atm = calls.nsmallest(1, "strike_diff").iloc[0]
                    current_iv = float(atm.get("impliedVolatility", 0) or 0)
        except Exception:
            pass

        # Get historical daily closes to compute rolling HV (proxy for IV history)
        hist = tk.history(period=f"{lookback_days + 30}d", interval="1d")
        if hist.empty or len(hist) < 30:
            return {"symbol": symbol, "error": "Insufficient price history"}

        closes = hist["Close"].values

        # Compute 30-day rolling historical volatility
        log_returns = np.log(closes[1:] / closes[:-1])
        window = 21  # ~1 month
        hv_series = []
        for i in range(window, len(log_returns)):
            rv = np.std(log_returns[i-window:i]) * np.sqrt(252) * 100  # annualized %
            hv_series.append(rv)

        if not hv_series:
            return {"symbol": symbol, "error": "Could not compute HV"}

        current_hv = hv_series[-1]
        use_iv = current_iv * 100 if current_iv and current_iv > 0 else current_hv

        # IV Rank using HV history as proxy
        hv_array = np.array(hv_series[-lookback_days:])
        hv_min = float(np.min(hv_array))
        hv_max = float(np.max(hv_array))

        iv_rank = 0.0
        if hv_max > hv_min:
            iv_rank = (use_iv - hv_min) / (hv_max - hv_min) * 100

        # IV Percentile
        iv_pct = float(np.sum(hv_array < use_iv) / len(hv_array) * 100)

        # Recommendation
        if iv_rank < 25:
            rec = "✅ BUY OPTIONS — IV cheap (rank < 25)"
            ok_to_buy = True
        elif iv_rank < 50:
            rec = "🟡 ACCEPTABLE — IV moderate (rank 25-50)"
            ok_to_buy = True
        elif iv_rank < 75:
            rec = "🟠 CAUTIOUS — IV elevated (rank 50-75). Consider spread."
            ok_to_buy = False
        else:
            rec = "🔴 AVOID BUYING — IV very high (rank > 75). Premium crush risk."
            ok_to_buy = False

        return {
            "symbol": symbol,
            "current_iv_pct": round(use_iv, 1),
            "current_hv_pct": round(current_hv, 1),
            "iv_rank": round(iv_rank, 1),
            "iv_percentile": round(iv_pct, 1),
            "hv_52w_low": round(hv_min, 1),
            "hv_52w_high": round(hv_max, 1),
            "recommendation": rec,
            "ok_to_buy_options": ok_to_buy,
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}
