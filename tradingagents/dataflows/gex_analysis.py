"""
CooperCorp PRJ-002 — GEX (Gamma Exposure) Analysis
Calculates options market maker gamma positioning to identify key price levels.
"""
from typing import Optional


def calculate_gex_from_chain(options_chain: dict, spot_price: float) -> float:
    """
    Net GEX = sum(call_gamma * call_OI - put_gamma * put_OI) * 100 * spot^2 * 0.01
    options_chain: {calls: [{strike, gamma, openInterest}], puts: [...]}
    """
    try:
        net_gex = 0.0
        for call in options_chain.get("calls", []):
            gamma = float(call.get("gamma", 0) or 0)
            oi = float(call.get("openInterest", 0) or 0)
            net_gex += gamma * oi * 100 * (spot_price ** 2) * 0.01
        for put in options_chain.get("puts", []):
            gamma = float(put.get("gamma", 0) or 0)
            oi = float(put.get("openInterest", 0) or 0)
            net_gex -= gamma * oi * 100 * (spot_price ** 2) * 0.01
        return net_gex
    except Exception:
        return 0.0


def get_gex_levels(ticker: str) -> dict:
    """
    Fetch options chain and calculate GEX levels.
    Returns {call_wall, put_wall, gex_flip, net_gex, regime, call_wall_distance_pct, put_wall_distance_pct}
    """
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        spot = tk.fast_info.get("lastPrice", 0)
        if not spot:
            return {}

        expiries = tk.options
        if not expiries:
            return {}

        # Use nearest expiration
        chain = tk.option_chain(expiries[0])
        calls = chain.calls[["strike", "openInterest", "gamma"]].fillna(0)
        puts = chain.puts[["strike", "openInterest", "gamma"]].fillna(0)

        # GEX by strike
        gex_by_strike = {}
        for _, row in calls.iterrows():
            s = float(row["strike"])
            gex = float(row["gamma"]) * float(row["openInterest"]) * 100 * (float(spot) ** 2) * 0.01
            gex_by_strike[s] = gex_by_strike.get(s, 0) + gex
        for _, row in puts.iterrows():
            s = float(row["strike"])
            gex = float(row["gamma"]) * float(row["openInterest"]) * 100 * (float(spot) ** 2) * 0.01
            gex_by_strike[s] = gex_by_strike.get(s, 0) - gex

        if not gex_by_strike:
            return {}

        net_gex = sum(gex_by_strike.values())

        # Call wall = strike with highest positive GEX above spot
        call_candidates = {s: g for s, g in gex_by_strike.items() if s > spot and g > 0}
        call_wall = max(call_candidates, key=call_candidates.get) if call_candidates else spot * 1.05

        # Put wall = strike with most negative GEX below spot
        put_candidates = {s: g for s, g in gex_by_strike.items() if s < spot and g < 0}
        put_wall = min(put_candidates, key=lambda s: put_candidates[s]) if put_candidates else spot * 0.95

        # GEX flip = strike where GEX crosses zero (transition from pos to neg)
        sorted_strikes = sorted(gex_by_strike.keys())
        gex_flip = spot
        for i in range(len(sorted_strikes) - 1):
            s1, s2 = sorted_strikes[i], sorted_strikes[i + 1]
            if gex_by_strike[s1] * gex_by_strike[s2] < 0:
                gex_flip = (s1 + s2) / 2
                break

        spot_f = float(spot)
        return {
            "call_wall": call_wall,
            "put_wall": put_wall,
            "gex_flip": gex_flip,
            "net_gex": round(net_gex, 0),
            "regime": "positive_gamma" if net_gex >= 0 else "negative_gamma",
            "call_wall_distance_pct": round(abs(call_wall - spot_f) / spot_f * 100, 2),
            "put_wall_distance_pct": round(abs(put_wall - spot_f) / spot_f * 100, 2),
            "spot": spot_f
        }
    except Exception as e:
        return {}


def interpret_gex(gex_data: dict, current_price: float) -> str:
    """Human-readable GEX interpretation."""
    if not gex_data:
        return "GEX data unavailable"
    regime = gex_data.get("regime", "unknown")
    call_dist = gex_data.get("call_wall_distance_pct", 0)
    put_dist = gex_data.get("put_wall_distance_pct", 0)
    call_wall = gex_data.get("call_wall", 0)
    put_wall = gex_data.get("put_wall", 0)

    if regime == "positive_gamma":
        msg = f"✅ Positive gamma regime — MMs will pin price near {current_price:.2f}. "
        msg += f"Call wall: ${call_wall:.2f} (+{call_dist:.1f}%). Put wall: ${put_wall:.2f} (-{put_dist:.1f}%)."
    else:
        msg = f"⚡ Negative gamma regime — MMs amplify moves, higher volatility expected. "
        msg += f"Call wall: ${call_wall:.2f} (+{call_dist:.1f}%). Put wall: ${put_wall:.2f} (-{put_dist:.1f}%)."
    return msg
