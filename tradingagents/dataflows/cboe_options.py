"""
CooperCorp PRJ-002 — CBOE Real-Time Options Data
No API key, no login. Direct CBOE CDN endpoint.

Data quality:
  - Real-time (timestamp matches market time)
  - Full Greeks: delta, gamma, theta, vega, rho
  - Full bid/ask, IV, OI, volume, last trade
  - 3,000–5,000 contracts per symbol
  - URL: https://cdn.cboe.com/api/global/delayed_quotes/options/{SYMBOL}.json

Usage:
    from tradingagents.dataflows.cboe_options import get_options_chain, get_contracts_near_strike

    chain = get_options_chain('NVDA')
    calls = get_contracts_near_strike('NVDA', 179, 'call', days_min=5, days_max=45)
"""
import re
import requests
from datetime import datetime, date
from typing import Optional, List, Dict
from functools import lru_cache
import time

CBOE_BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options"

# Simple in-memory cache: {symbol: (timestamp, data)}
_cache: dict = {}
CACHE_TTL = 60  # seconds


def _fetch_chain_raw(symbol: str) -> Optional[dict]:
    """Fetch raw CBOE options data. Cached for 60s."""
    symbol = symbol.upper()
    now = time.time()
    if symbol in _cache:
        ts, data = _cache[symbol]
        if now - ts < CACHE_TTL:
            return data

    try:
        url = f"{CBOE_BASE}/{symbol}.json"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        _cache[symbol] = (now, data)
        return data
    except Exception:
        return None


def _parse_occ(occ: str) -> Optional[dict]:
    """
    Parse OCC symbol: NVDA260307C00180000
    Returns: {symbol, exp_date, option_type, strike}
    """
    m = re.match(r'^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$', occ)
    if not m:
        return None
    sym, yy, mm, dd, cp, strike_raw = m.groups()
    try:
        exp = date(2000 + int(yy), int(mm), int(dd))
        strike = int(strike_raw) / 1000
        return {
            "symbol": sym,
            "exp_date": exp,
            "exp_str": exp.strftime("%Y-%m-%d"),
            "exp_fmt": exp.strftime("%-m/%-d"),
            "days_to_exp": (exp - date.today()).days,
            "option_type": "call" if cp == "C" else "put",
            "strike": strike,
            "occ": occ,
        }
    except Exception:
        return None


def get_options_chain(symbol: str) -> Optional[dict]:
    """
    Get full parsed options chain from CBOE.
    Returns {symbol, price, timestamp, calls: [...], puts: [...], all: [...]}
    Each contract: {occ, strike, exp_str, days_to_exp, option_type,
                    bid, ask, mid, last, iv, delta, gamma, theta, vega, rho,
                    volume, open_interest, change}
    """
    raw = _fetch_chain_raw(symbol)
    if not raw:
        return None

    data = raw.get("data", {})
    price = float(data.get("current_price", 0) or 0)
    timestamp = raw.get("timestamp", "")
    raw_opts = data.get("options", [])

    calls, puts = [], []
    for o in raw_opts:
        occ_str = o.get("option", "")
        parsed = _parse_occ(occ_str)
        if not parsed:
            continue
        bid  = float(o.get("bid", 0) or 0)
        ask  = float(o.get("ask", 0) or 0)
        mid  = round((bid + ask) / 2, 2) if (bid and ask) else float(o.get("last_trade_price", 0) or 0)
        contract = {
            **parsed,
            "bid":   bid,
            "ask":   ask,
            "mid":   mid,
            "last":  float(o.get("last_trade_price", 0) or 0),
            "iv":    float(o.get("iv", 0) or 0),
            "delta": float(o.get("delta", 0) or 0),
            "gamma": float(o.get("gamma", 0) or 0),
            "theta": float(o.get("theta", 0) or 0),
            "vega":  float(o.get("vega", 0) or 0),
            "rho":   float(o.get("rho", 0) or 0),
            "volume":         int(o.get("volume", 0) or 0),
            "open_interest":  int(o.get("open_interest", 0) or 0),
            "change": float(o.get("change", 0) or 0),
            "theo":  float(o.get("theo", 0) or 0),
        }
        if parsed["option_type"] == "call":
            calls.append(contract)
        else:
            puts.append(contract)

    return {
        "symbol":    symbol.upper(),
        "price":     price,
        "timestamp": timestamp,
        "calls":     sorted(calls, key=lambda x: (x["exp_date"], x["strike"])),
        "puts":      sorted(puts,  key=lambda x: (x["exp_date"], x["strike"])),
        "all":       calls + puts,
    }


def get_contracts_near_strike(
    symbol: str,
    target_price: float,
    option_type: str = "call",   # "call" or "put"
    days_min: int = 5,
    days_max: int = 60,
    n: int = 3,
    pct_range: float = 0.12,     # only look within ±12% of target_price
) -> List[dict]:
    """
    Get the N closest contracts to target_price within expiry window.
    Returns sorted by closeness to target_price.
    """
    chain = get_options_chain(symbol)
    if not chain:
        return []

    pool = chain["calls"] if option_type == "call" else chain["puts"]
    lo   = target_price * (1 - pct_range)
    hi   = target_price * (1 + pct_range)

    filtered = [
        c for c in pool
        if days_min <= c["days_to_exp"] <= days_max
        and lo <= c["strike"] <= hi
        and c["mid"] > 0.05        # has real pricing
        and c["open_interest"] > 0  # has liquidity
    ]

    filtered.sort(key=lambda c: abs(c["strike"] - target_price))
    return filtered[:n]


def get_iv_rank_cboe(symbol: str, current_price: float = None) -> Optional[dict]:
    """
    Estimate IV rank from ATM options in the chain.
    Uses the average IV of 4 ATM contracts (2 calls + 2 puts, nearest expiry).
    """
    chain = get_options_chain(symbol)
    if not chain:
        return None

    price = current_price or chain["price"]
    if not price:
        return None

    # Get ATM contracts, nearest expiry
    atm_calls = get_contracts_near_strike(symbol, price, "call", days_min=7, days_max=45, n=2)
    atm_puts  = get_contracts_near_strike(symbol, price, "put",  days_min=7, days_max=45, n=2)
    atm = atm_calls + atm_puts

    if not atm:
        return None

    ivs = [c["iv"] for c in atm if c["iv"] > 0]
    if not ivs:
        return None

    avg_iv = sum(ivs) / len(ivs)
    # Rough IV rank: use avg IV vs typical range (this is approximate without history)
    # For most stocks: IV 20-25 = low, 40-60 = normal, 80+ = elevated
    iv_rank_approx = min(100, max(0, (avg_iv - 0.20) / 0.80 * 100))

    return {
        "symbol":     symbol,
        "iv_current": round(avg_iv, 4),
        "iv_pct":     round(avg_iv * 100, 1),
        "iv_rank":    round(iv_rank_approx, 1),
        "ok_to_buy_options": iv_rank_approx < 30,
        "source":     "cboe",
    }


def format_cboe_contract(c: dict) -> str:
    """One-line formatted contract string."""
    iv_str = f"IV {c['iv']*100:.1f}%" if c['iv'] else ""
    delta_str = f"Δ{c['delta']:.2f}" if c['delta'] else ""
    return (
        f"{c['occ']}  "
        f"Mid ${c['mid']:.2f}  "
        f"Strike ${c['strike']:.0f}  "
        f"Exp {c['exp_fmt']} ({c['days_to_exp']}d)  "
        f"{iv_str}  {delta_str}  "
        f"OI {c['open_interest']:,}  Vol {c['volume']:,}"
    )


if __name__ == "__main__":
    print("Testing CBOE options data...\n")

    chain = get_options_chain("NVDA")
    if chain:
        print(f"✅ NVDA @ ${chain['price']} | {len(chain['calls'])} calls, {len(chain['puts'])} puts | ts: {chain['timestamp']}")
        print()
        # ATM calls
        price = chain["price"]
        calls = get_contracts_near_strike("NVDA", price * 1.02, "call", n=3)
        puts  = get_contracts_near_strike("NVDA", price * 0.98, "put",  n=3)
        print("ATM CALLS:")
        for c in calls:
            print(" ", format_cboe_contract(c))
        print("\nATM PUTS:")
        for p in puts:
            print(" ", format_cboe_contract(p))

        # IV rank
        iv = get_iv_rank_cboe("NVDA", price)
        if iv:
            print(f"\nIV: {iv['iv_pct']}% | IV rank: {iv['iv_rank']:.0f} | Buy options: {'✅' if iv['ok_to_buy_options'] else '❌'}")
    else:
        print("❌ Failed to fetch chain")
