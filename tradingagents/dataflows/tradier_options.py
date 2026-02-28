"""
CooperCorp PRJ-002 — Tradier Options Data Source
Real-time options chains with greeks. Faster refresh than CBOE + more strike coverage.

Setup (HITL REQUIRED):
  1. Sign up at https://dashboard.tradier.com/signup
  2. Create a free brokerage account (no funding required for API access)
  3. Get API token from Settings → API Access
  4. Add to .env: TRADIER_API_KEY=your_token_here

Usage:
  from tradingagents.dataflows.tradier_options import TradierOptions

  to = TradierOptions()
  chain = to.get_chain("NVDA", days_min=7, days_max=45)
  # Returns: {"calls": [...], "puts": [...], "price": float, "source": "tradier"}

Fallback:
  If TRADIER_API_KEY not set or request fails, returns None.
  options_chain.py will fall back to CBOE → yfinance chain.
"""
import os
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict

BASE_URL = "https://api.tradier.com/v1"


class TradierOptions:
    """Tradier options chain fetcher."""

    def __init__(self):
        self.api_key = os.getenv("TRADIER_API_KEY", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def is_available(self) -> bool:
        """Check if Tradier API key is configured."""
        return bool(self.api_key)

    def get_chain(
        self,
        symbol: str,
        days_min: int = 5,
        days_max: int = 60,
    ) -> Optional[Dict]:
        """
        Fetch options chain for symbol.

        Returns:
            {
                "symbol": str,
                "price": float,
                "calls": [{strike, bid, ask, mid, iv, delta, gamma, theta, vega, volume, oi, exp_str, days_to_exp, ...}],
                "puts": [...],
                "expirations": [str],
                "source": "tradier",
            }
        """
        if not self.is_available():
            return None

        try:
            # Get expirations
            exp_r = requests.get(
                f"{BASE_URL}/markets/options/expirations",
                headers=self.headers,
                params={"symbol": symbol, "includeAllRoots": "true"},
                timeout=10,
            )
            if exp_r.status_code != 200:
                return None
            exp_data = exp_r.json().get("expirations", {}).get("expiration", [])
            if not exp_data:
                return None

            # Filter expirations by date range
            today = datetime.now()
            expirations = []
            for e in exp_data:
                exp_date = datetime.strptime(e, "%Y-%m-%d")
                days = (exp_date - today).days
                if days_min <= days <= days_max:
                    expirations.append((e, days))

            if not expirations:
                return None

            # Get current quote for underlying price
            quote_r = requests.get(
                f"{BASE_URL}/markets/quotes",
                headers=self.headers,
                params={"symbols": symbol},
                timeout=10,
            )
            if quote_r.status_code != 200:
                return None
            quote_data = quote_r.json().get("quotes", {}).get("quote", {})
            price = float(quote_data.get("last", 0) or quote_data.get("bid", 0) or 0)
            if not price:
                return None

            # Fetch chain for each expiration (use nearest first)
            all_calls, all_puts = [], []
            for exp_str, days_to_exp in expirations[:3]:  # Limit to 3 nearest
                chain_r = requests.get(
                    f"{BASE_URL}/markets/options/chains",
                    headers=self.headers,
                    params={"symbol": symbol, "expiration": exp_str, "greeks": "true"},
                    timeout=10,
                )
                if chain_r.status_code != 200:
                    continue
                options = chain_r.json().get("options", {}).get("option", [])
                if not options:
                    continue

                for opt in options:
                    greeks = opt.get("greeks", {}) or {}
                    contract = {
                        "symbol": symbol,
                        "occ": opt.get("symbol", ""),
                        "strike": float(opt.get("strike", 0)),
                        "option_type": opt.get("option_type", "").lower(),
                        "bid": float(opt.get("bid", 0) or 0),
                        "ask": float(opt.get("ask", 0) or 0),
                        "last": float(opt.get("last", 0) or 0),
                        "mid": round((float(opt.get("bid", 0) or 0) + float(opt.get("ask", 0) or 0)) / 2, 2),
                        "iv": float(greeks.get("smv_vol", 0) or greeks.get("mid_iv", 0) or 0),
                        "delta": float(greeks.get("delta", 0) or 0),
                        "gamma": float(greeks.get("gamma", 0) or 0),
                        "theta": float(greeks.get("theta", 0) or 0),
                        "vega": float(greeks.get("vega", 0) or 0),
                        "volume": int(opt.get("volume", 0) or 0),
                        "open_interest": int(opt.get("open_interest", 0) or 0),
                        "exp_str": exp_str,
                        "exp_fmt": datetime.strptime(exp_str, "%Y-%m-%d").strftime("%-m/%-d"),
                        "days_to_exp": days_to_exp,
                        "in_the_money": (opt.get("option_type") == "call" and float(opt.get("strike", 0)) < price)
                                        or (opt.get("option_type") == "put" and float(opt.get("strike", 0)) > price),
                        "source": "tradier",
                    }
                    if opt.get("option_type") == "call":
                        all_calls.append(contract)
                    else:
                        all_puts.append(contract)

            if not all_calls and not all_puts:
                return None

            return {
                "symbol": symbol,
                "price": price,
                "calls": sorted(all_calls, key=lambda x: x["strike"]),
                "puts": sorted(all_puts, key=lambda x: x["strike"], reverse=True),
                "expirations": [e[0] for e in expirations],
                "source": "tradier",
            }

        except Exception as e:
            return None

    def get_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        """Batch quote fetch for underlying prices."""
        if not self.is_available() or not symbols:
            return {}
        try:
            r = requests.get(
                f"{BASE_URL}/markets/quotes",
                headers=self.headers,
                params={"symbols": ",".join(symbols)},
                timeout=10,
            )
            if r.status_code != 200:
                return {}
            quotes = r.json().get("quotes", {}).get("quote", [])
            if not isinstance(quotes, list):
                quotes = [quotes]
            return {
                q["symbol"]: {
                    "price": float(q.get("last", 0) or 0),
                    "bid": float(q.get("bid", 0) or 0),
                    "ask": float(q.get("ask", 0) or 0),
                    "volume": int(q.get("volume", 0) or 0),
                }
                for q in quotes
            }
        except Exception:
            return {}


# ── Convenience functions ─────────────────────────────────────────────────────

def get_tradier_chain(symbol: str, days_min: int = 5, days_max: int = 60) -> Optional[Dict]:
    """Get Tradier options chain (or None if unavailable)."""
    to = TradierOptions()
    return to.get_chain(symbol, days_min, days_max)


def is_tradier_available() -> bool:
    """Check if Tradier API is configured."""
    return bool(os.getenv("TRADIER_API_KEY", ""))


if __name__ == "__main__":
    # Quick test
    to = TradierOptions()
    if not to.is_available():
        print("⚠️  TRADIER_API_KEY not set. Add to .env:")
        print("   TRADIER_API_KEY=your_token_here")
        print("\nSign up at: https://dashboard.tradier.com/signup")
    else:
        chain = to.get_chain("NVDA")
        if chain:
            print(f"✅ Tradier API working — {len(chain['calls'])} calls, {len(chain['puts'])} puts for NVDA")
            print(f"   Price: ${chain['price']:.2f}")
        else:
            print("❌ Tradier API call failed")
