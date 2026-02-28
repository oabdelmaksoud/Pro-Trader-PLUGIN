"""
CooperCorp PRJ-002 — Multi-Strategy Options Engine
Data source priority: Tradier → CBOE → yfinance (15-min delayed)
  - Tradier: fastest refresh, best greeks (requires free API token)
  - CBOE: real-time, no API key needed
  - yfinance: 15-min delayed fallback
Suggests optimal strategies across DIRECTIONAL, NEUTRAL, and INCOME plays
based on IV rank, signal direction, and market context.

Strategy selection logic:
─────────────────────────────────────────────────────────────────────────
  IV rank < 25  (cheap IV)  → prefer BUYING premium (calls, puts, straddles)
  IV rank > 60  (rich IV)   → prefer SELLING premium (spreads, iron condors, CC)
  Strong signal (score≥7.5) → directional (calls or puts, tight OTM)
  Neutral/weak signal       → non-directional (straddle, strangle, IC)
  Position open             → income play (covered call, CSP)

Strategy catalogue:
  DIRECTIONAL  → Long Call, Long Put, Bull Call Spread, Bear Put Spread
  NEUTRAL/VOL  → Long Straddle, Long Strangle, Short Straddle, Iron Condor
  INCOME       → Covered Call, Cash-Secured Put, Put Credit Spread
"""
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _get_cboe_chain(ticker: str):
    """Get CBOE options chain (real-time, no API key)."""
    try:
        from tradingagents.dataflows.cboe_options import get_options_chain
        return get_options_chain(ticker)
    except Exception:
        return None


def _get_tradier_chain(ticker: str):
    """Get Tradier options chain (fastest, requires TRADIER_API_KEY)."""
    try:
        from tradingagents.dataflows.tradier_options import get_tradier_chain
        return get_tradier_chain(ticker)
    except Exception:
        return None

def _get_chain(ticker: str, exp_str: str):
    """Legacy yfinance chain — used as fallback."""
    tk = yf.Ticker(ticker)
    return tk.option_chain(exp_str)

def _mid(row) -> float:
    bid = float(row.get("bid", 0) or 0)
    ask = float(row.get("ask", 0) or 0)
    last = float(row.get("lastPrice", 0) or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last

def _find_strike(options, target_price, n=1):
    """Find closest N strikes to target_price."""
    df = options.copy()
    df["_diff"] = abs(df["strike"] - target_price)
    return df.nsmallest(n, "_diff").iloc[0] if n == 1 else df.nsmallest(n, "_diff")

def _get_expirations(tk, min_days=5, max_days=60):
    today = datetime.today()
    out = []
    for exp in (tk.options or []):
        exp_dt = datetime.strptime(exp, "%Y-%m-%d")
        days = (exp_dt - today).days
        if min_days <= days <= max_days:
            out.append((exp, days, exp_dt))
    return sorted(out, key=lambda x: x[1])

def _cboe_contract_to_dict(c: dict, label: str, strategy: str, direction: str) -> dict:
    """Convert CBOE contract to our standard contract dict format."""
    entry = c["mid"] or c["last"]
    if not entry:
        return None
    sl = round(entry * 0.75, 2)
    tp = round(entry * 1.80, 2)
    rr = round((tp - entry) / max(entry - sl, 0.01), 1)
    return {
        "label":        label,
        "strategy":     strategy,
        "direction":    direction,
        "ticker":       c["symbol"],
        "type":         f"{'Call' if c['option_type']=='call' else 'Put'} ${c['strike']:g}",
        "strike":       c["strike"],
        "expiry":       c["exp_str"],
        "expiry_fmt":   c["exp_fmt"],
        "days_to_exp":  c["days_to_exp"],
        "entry":        round(entry, 2),
        "sl":           sl,
        "tp":           tp,
        "rr":           rr,
        "max_loss":     round(entry * 100, 2),
        "max_profit":   "unlimited",
        "iv":           round(c["iv"] * 100, 1) if c.get("iv") else None,
        "delta":        c.get("delta"),
        "volume":       c.get("volume", 0),
        "oi":           c.get("open_interest", 0),
        "occ":          c.get("occ"),
        "source":       "cboe",
        "note": f"Delta {c.get('delta',0):.2f} | Profit if moves past ${c['strike'] + entry:.2f}" if c.get('option_type')=='call' else f"Delta {c.get('delta',0):.2f} | Profit below ${c['strike'] - entry:.2f}",
    }

def _contract_dict(base: dict, strategy: str, direction: str, extra: dict = None) -> dict:
    d = {**base, "strategy": strategy, "direction": direction}
    if extra:
        d.update(extra)
    return d


# ── STRATEGY BUILDERS ─────────────────────────────────────────────────────────

def _long_call(tk, exp_str, days, exp_dt, price, label="🟢 LONG CALL") -> Optional[dict]:
    try:
        chain = tk.option_chain(exp_str)
        row = _find_strike(chain.calls, price * 1.02)
        entry = _mid(row)
        if entry < 0.05: return None
        strike = float(row["strike"])
        sl = round(entry * 0.75, 2)
        tp = round(entry * 1.80, 2)
        return {
            "label": label,
            "strategy": "Long Call",
            "direction": "BULLISH",
            "ticker": tk.ticker,
            "type": "Call",
            "strike": strike,
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "rr": round((tp - entry) / max(entry - sl, 0.01), 1),
            "max_loss": round(entry * 100, 2),
            "max_profit": "unlimited",
            "iv": round(float(row.get("impliedVolatility", 0) or 0) * 100, 1),
            "volume": int(row.get("volume", 0) or 0),
            "oi": int(row.get("openInterest", 0) or 0),
            "note": f"Profit if {tk.ticker} > ${strike + entry:.2f} at exp",
        }
    except Exception:
        return None

def _long_put(tk, exp_str, days, exp_dt, price, label="🔴 LONG PUT") -> Optional[dict]:
    try:
        chain = tk.option_chain(exp_str)
        row = _find_strike(chain.puts, price * 0.98)
        entry = _mid(row)
        if entry < 0.05: return None
        strike = float(row["strike"])
        sl = round(entry * 0.75, 2)
        tp = round(entry * 1.80, 2)
        return {
            "label": label,
            "strategy": "Long Put",
            "direction": "BEARISH",
            "ticker": tk.ticker,
            "type": "Put",
            "strike": strike,
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "rr": round((tp - entry) / max(entry - sl, 0.01), 1),
            "max_loss": round(entry * 100, 2),
            "max_profit": f"up to ${round(strike * 100, 0):.0f}/contract",
            "iv": round(float(row.get("impliedVolatility", 0) or 0) * 100, 1),
            "volume": int(row.get("volume", 0) or 0),
            "oi": int(row.get("openInterest", 0) or 0),
            "note": f"Profit if {tk.ticker} < ${strike - entry:.2f} at exp",
        }
    except Exception:
        return None

def _bull_call_spread(tk, exp_str, days, exp_dt, price, label="📈 BULL CALL SPREAD") -> Optional[dict]:
    """Buy ATM call, sell OTM call. Reduces cost, caps profit."""
    try:
        chain = tk.option_chain(exp_str)
        long_row = _find_strike(chain.calls, price * 1.01)
        short_row = _find_strike(chain.calls, price * 1.06)
        long_entry = _mid(long_row)
        short_credit = _mid(short_row)
        if long_entry < 0.05 or short_credit < 0.01: return None
        net_debit = round(long_entry - short_credit, 2)
        if net_debit <= 0: return None
        long_strike = float(long_row["strike"])
        short_strike = float(short_row["strike"])
        max_profit = round((short_strike - long_strike - net_debit) * 100, 2)
        max_loss = round(net_debit * 100, 2)
        return {
            "label": label,
            "strategy": "Bull Call Spread",
            "direction": "BULLISH",
            "ticker": tk.ticker,
            "type": f"Call ${long_strike:g}/{short_strike:g}",
            "strike": long_strike,
            "strike2": short_strike,
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": net_debit,
            "sl": round(net_debit * 0.5, 2),
            "tp": round(max_profit / 100, 2),
            "rr": round(max_profit / max_loss, 1) if max_loss > 0 else 0,
            "max_loss": max_loss,
            "max_profit": f"${max_profit:.0f}/contract",
            "iv": round(float(long_row.get("impliedVolatility", 0) or 0) * 100, 1),
            "volume": int(long_row.get("volume", 0) or 0),
            "oi": int(long_row.get("openInterest", 0) or 0),
            "note": f"Cheaper than naked call. Max profit at ${short_strike:g}",
        }
    except Exception:
        return None

def _bear_put_spread(tk, exp_str, days, exp_dt, price, label="📉 BEAR PUT SPREAD") -> Optional[dict]:
    """Buy ATM put, sell OTM put. Reduces cost, caps profit."""
    try:
        chain = tk.option_chain(exp_str)
        long_row = _find_strike(chain.puts, price * 0.99)
        short_row = _find_strike(chain.puts, price * 0.94)
        long_entry = _mid(long_row)
        short_credit = _mid(short_row)
        if long_entry < 0.05 or short_credit < 0.01: return None
        net_debit = round(long_entry - short_credit, 2)
        if net_debit <= 0: return None
        long_strike = float(long_row["strike"])
        short_strike = float(short_row["strike"])
        max_profit = round((long_strike - short_strike - net_debit) * 100, 2)
        max_loss = round(net_debit * 100, 2)
        return {
            "label": label,
            "strategy": "Bear Put Spread",
            "direction": "BEARISH",
            "ticker": tk.ticker,
            "type": f"Put ${long_strike:g}/{short_strike:g}",
            "strike": long_strike,
            "strike2": short_strike,
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": net_debit,
            "sl": round(net_debit * 0.5, 2),
            "tp": round(max_profit / 100, 2),
            "rr": round(max_profit / max_loss, 1) if max_loss > 0 else 0,
            "max_loss": max_loss,
            "max_profit": f"${max_profit:.0f}/contract",
            "iv": round(float(long_row.get("impliedVolatility", 0) or 0) * 100, 1),
            "volume": int(long_row.get("volume", 0) or 0),
            "oi": int(long_row.get("openInterest", 0) or 0),
            "note": f"Cheaper than naked put. Max profit at ${short_strike:g}",
        }
    except Exception:
        return None

def _long_straddle(tk, exp_str, days, exp_dt, price, label="⚡ LONG STRADDLE") -> Optional[dict]:
    """Buy ATM call + ATM put. Profit on big move either direction."""
    try:
        chain = tk.option_chain(exp_str)
        call_row = _find_strike(chain.calls, price)
        put_row = _find_strike(chain.puts, price)
        call_entry = _mid(call_row)
        put_entry = _mid(put_row)
        if call_entry < 0.05 or put_entry < 0.05: return None
        total_cost = round(call_entry + put_entry, 2)
        strike = float(call_row["strike"])
        breakeven_up = round(strike + total_cost, 2)
        breakeven_dn = round(strike - total_cost, 2)
        iv_avg = round(((float(call_row.get("impliedVolatility",0) or 0) +
                         float(put_row.get("impliedVolatility",0) or 0)) / 2) * 100, 1)
        return {
            "label": label,
            "strategy": "Long Straddle",
            "direction": "NEUTRAL (vol play)",
            "ticker": tk.ticker,
            "type": f"Call+Put ${strike:g}",
            "strike": strike,
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": total_cost,
            "sl": round(total_cost * 0.40, 2),
            "tp": round(total_cost * 2.0, 2),
            "rr": 1.5,
            "max_loss": round(total_cost * 100, 2),
            "max_profit": "unlimited (both sides)",
            "breakeven_up": breakeven_up,
            "breakeven_dn": breakeven_dn,
            "iv": iv_avg,
            "volume": int(call_row.get("volume", 0) or 0),
            "oi": int(call_row.get("openInterest", 0) or 0),
            "note": f"Profit if ${tk.ticker} > ${breakeven_up} or < ${breakeven_dn}. Best before catalysts.",
        }
    except Exception:
        return None

def _iron_condor(tk, exp_str, days, exp_dt, price, label="🦅 IRON CONDOR") -> Optional[dict]:
    """Sell OTM call spread + put spread. Profit in range."""
    try:
        chain = tk.option_chain(exp_str)
        # Sell 5% OTM call, buy 10% OTM call
        sc_row = _find_strike(chain.calls, price * 1.05)
        lc_row = _find_strike(chain.calls, price * 1.10)
        # Sell 5% OTM put, buy 10% OTM put
        sp_row = _find_strike(chain.puts, price * 0.95)
        lp_row = _find_strike(chain.puts, price * 0.90)
        sc = _mid(sc_row); lc = _mid(lc_row)
        sp = _mid(sp_row); lp = _mid(lp_row)
        if any(v < 0.01 for v in [sc, lc, sp, lp]): return None
        net_credit = round((sc - lc + sp - lp), 2)
        if net_credit <= 0: return None
        call_spread_w = float(lc_row["strike"]) - float(sc_row["strike"])
        max_loss = round((call_spread_w - net_credit) * 100, 2)
        return {
            "label": label,
            "strategy": "Iron Condor",
            "direction": "NEUTRAL (range-bound)",
            "ticker": tk.ticker,
            "type": f"IC ${float(sp_row['strike']):g}/{float(sc_row['strike']):g}",
            "strike": float(sp_row["strike"]),
            "strike2": float(sc_row["strike"]),
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": net_credit,
            "sl": round(net_credit * 2, 2),
            "tp": round(net_credit * 0.5, 2),
            "rr": round(net_credit * 100 / max(max_loss, 1), 2),
            "max_loss": max_loss,
            "max_profit": f"${round(net_credit*100,0):.0f}/contract (keep premium)",
            "iv": round(float(sc_row.get("impliedVolatility",0) or 0) * 100, 1),
            "volume": int(sc_row.get("volume",0) or 0),
            "oi": int(sc_row.get("openInterest",0) or 0),
            "note": f"Profit if price stays between ${float(sp_row['strike']):g}–${float(sc_row['strike']):g} until {exp_dt.strftime('%-m/%-d')}",
        }
    except Exception:
        return None

def _cash_secured_put(tk, exp_str, days, exp_dt, price, label="💰 CASH-SECURED PUT") -> Optional[dict]:
    """Sell OTM put. Collect premium; willing to buy at that price."""
    try:
        chain = tk.option_chain(exp_str)
        row = _find_strike(chain.puts, price * 0.95)
        credit = _mid(row)
        if credit < 0.05: return None
        strike = float(row["strike"])
        cost_basis = round(strike - credit, 2)
        return {
            "label": label,
            "strategy": "Cash-Secured Put",
            "direction": "INCOME / BULLISH",
            "ticker": tk.ticker,
            "type": f"Put ${strike:g} (sell)",
            "strike": strike,
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": credit,
            "sl": round(credit * 3, 2),
            "tp": 0.05,
            "rr": round(credit / max(strike - credit, 1), 3),
            "max_loss": round((strike - credit) * 100, 2),
            "max_profit": f"${round(credit*100,0):.0f}/contract (keep premium)",
            "cost_basis": cost_basis,
            "iv": round(float(row.get("impliedVolatility",0) or 0) * 100, 1),
            "volume": int(row.get("volume",0) or 0),
            "oi": int(row.get("openInterest",0) or 0),
            "note": f"Effective buy price ${cost_basis}. Only use if willing to own {tk.ticker}.",
        }
    except Exception:
        return None

def _covered_call(tk, exp_str, days, exp_dt, price, label="📤 COVERED CALL") -> Optional[dict]:
    """Sell OTM call against existing position to collect premium."""
    try:
        chain = tk.option_chain(exp_str)
        row = _find_strike(chain.calls, price * 1.05)
        credit = _mid(row)
        if credit < 0.05: return None
        strike = float(row["strike"])
        return {
            "label": label,
            "strategy": "Covered Call",
            "direction": "INCOME / MILDLY BULLISH",
            "ticker": tk.ticker,
            "type": f"Call ${strike:g} (sell)",
            "strike": strike,
            "expiry": exp_str,
            "expiry_fmt": exp_dt.strftime("%-m/%-d"),
            "days_to_exp": days,
            "entry": credit,
            "sl": None,
            "tp": 0.05,
            "rr": None,
            "max_loss": None,
            "max_profit": f"${round(credit*100,0):.0f}/contract + stock gains to ${strike}",
            "iv": round(float(row.get("impliedVolatility",0) or 0) * 100, 1),
            "volume": int(row.get("volume",0) or 0),
            "oi": int(row.get("openInterest",0) or 0),
            "note": f"Requires 100 shares of {tk.ticker}. Caps upside at ${strike}.",
        }
    except Exception:
        return None


# ── MAIN ENGINE ───────────────────────────────────────────────────────────────

def get_options_strategies(
    symbol: str,
    direction: str = "LONG",
    current_price: Optional[float] = None,
    iv_rank: Optional[float] = None,
    score: Optional[float] = None,
    has_position: bool = False,
) -> dict:
    """
    Returns a multi-strategy options recommendation dict.

    Args:
        symbol: Ticker symbol
        direction: 'LONG' (bullish signal) or 'SHORT' (bearish)
        current_price: override price
        iv_rank: 0-100, if known (< 25 = cheap, > 60 = rich)
        score: signal score 0-10 (higher = more conviction)
        has_position: True if already holding this stock

    Returns:
        {
          "ticker": str,
          "price": float,
          "iv_rank": float,
          "best_strategy": str,
          "directional": [...],
          "neutral": [...],
          "income": [...],
          "summary": str,
        }
    """
    try:
        # ── Try Tradier first (fastest, requires API key) ──
        tradier_chain = _get_tradier_chain(symbol)
        use_tradier = tradier_chain is not None and len(tradier_chain.get("calls", [])) > 0

        # ── Fallback to CBOE (real-time, no API key) ──
        cboe_chain = None
        use_cboe = False
        if not use_tradier:
            cboe_chain = _get_cboe_chain(symbol)
            use_cboe = cboe_chain is not None and len(cboe_chain.get("calls", [])) > 0

        # Get current price (Tradier → CBOE → Alpaca → yfinance)
        if not current_price:
            if use_tradier and tradier_chain.get("price"):
                current_price = tradier_chain["price"]
            elif use_cboe and cboe_chain.get("price"):
                current_price = cboe_chain["price"]
            else:
                try:
                    from tradingagents.dataflows.realtime_quotes import get_price as rt_price
                    current_price = rt_price(symbol)
                except Exception:
                    pass
            if not current_price:
                tk = yf.Ticker(symbol)
                hist = tk.history(period="1d", interval="1m")
                current_price = float(hist["Close"].iloc[-1]) if not hist.empty else 0
        if not current_price:
            return {"ticker": symbol, "error": "price unavailable"}

        # If CBOE works (and Tradier unavailable), build strategies from CBOE contracts
        if use_cboe and not use_tradier:
            from tradingagents.dataflows.cboe_options import get_contracts_near_strike
            labels_dir  = ["🥇 BEST", "🥈 ALT", "🎰 SWING"]
            labels_neu  = ["⚡ VOL PLAY", "🦅 SPREAD"]
            labels_inc  = ["💰 INCOME"]

            directional, neutral, income = [], [], []
            iv_rank_cboe = None

            if direction == "LONG":
                # ATM call
                calls = get_contracts_near_strike(symbol, current_price * 1.01, "call", days_min=5, days_max=21, n=1)
                calls += get_contracts_near_strike(symbol, current_price * 1.04, "call", days_min=14, days_max=45, n=1)
                calls += get_contracts_near_strike(symbol, current_price * 1.08, "call", days_min=21, days_max=60, n=1)
                for i, c in enumerate(calls):
                    dc = _cboe_contract_to_dict(c, labels_dir[i] if i < len(labels_dir) else "📋", "Long Call", "BULLISH")
                    if dc: directional.append(dc)
            else:  # SHORT
                puts = get_contracts_near_strike(symbol, current_price * 0.99, "put", days_min=5, days_max=21, n=1)
                puts += get_contracts_near_strike(symbol, current_price * 0.96, "put", days_min=14, days_max=45, n=1)
                puts += get_contracts_near_strike(symbol, current_price * 0.92, "put", days_min=21, days_max=60, n=1)
                for i, p in enumerate(puts):
                    dc = _cboe_contract_to_dict(p, labels_dir[i] if i < len(labels_dir) else "📋", "Long Put", "BEARISH")
                    if dc: directional.append(dc)

            # Neutral: straddle (ATM call + put, same expiry ~3 weeks)
            nc = get_contracts_near_strike(symbol, current_price, "call", days_min=14, days_max=35, n=1)
            np_ = get_contracts_near_strike(symbol, current_price, "put", days_min=14, days_max=35, n=1)
            if nc and np_:
                c_entry = nc[0]["mid"]; p_entry = np_[0]["mid"]
                total = round(c_entry + p_entry, 2)
                be_up = round(nc[0]["strike"] + total, 2)
                be_dn = round(nc[0]["strike"] - total, 2)
                neutral.append({
                    "label": "⚡ LONG STRADDLE", "strategy": "Long Straddle",
                    "direction": "NEUTRAL (vol play)", "ticker": symbol,
                    "type": f"Call+Put ${nc[0]['strike']:g}", "strike": nc[0]["strike"],
                    "expiry": nc[0]["exp_str"], "expiry_fmt": nc[0]["exp_fmt"],
                    "days_to_exp": nc[0]["days_to_exp"],
                    "entry": total, "sl": round(total * 0.40, 2), "tp": round(total * 2.0, 2),
                    "rr": 1.5, "max_loss": round(total * 100, 2),
                    "max_profit": "unlimited (both sides)",
                    "breakeven_up": be_up, "breakeven_dn": be_dn,
                    "iv": round(nc[0].get("iv", 0) * 100, 1),
                    "volume": nc[0].get("volume", 0), "oi": nc[0].get("open_interest", 0),
                    "source": "cboe",
                    "note": f"Profit if ${symbol} > ${be_up} or < ${be_dn}",
                })

            # Income: CSP
            csp_puts = get_contracts_near_strike(symbol, current_price * 0.95, "put", days_min=5, days_max=21, n=1)
            if csp_puts:
                cp = csp_puts[0]
                credit = cp["mid"]
                income.append({
                    "label": "💰 CASH-SECURED PUT", "strategy": "Cash-Secured Put",
                    "direction": "INCOME / BULLISH", "ticker": symbol,
                    "type": f"Put ${cp['strike']:g} (sell)", "strike": cp["strike"],
                    "expiry": cp["exp_str"], "expiry_fmt": cp["exp_fmt"],
                    "days_to_exp": cp["days_to_exp"],
                    "entry": round(credit, 2), "sl": round(credit * 3, 2), "tp": 0.05,
                    "rr": round(credit / max(cp["strike"] - credit, 1), 3),
                    "max_loss": round((cp["strike"] - credit) * 100, 2),
                    "max_profit": f"${round(credit*100,0):.0f}/contract (keep premium)",
                    "iv": round(cp.get("iv", 0) * 100, 1),
                    "volume": cp.get("volume", 0), "oi": cp.get("open_interest", 0),
                    "source": "cboe",
                    "note": f"Effective buy price ${round(cp['strike'] - credit, 2)}. Only use if willing to own {symbol}.",
                })

            # IV rank from CBOE
            if not iv_rank:
                try:
                    from tradingagents.dataflows.cboe_options import get_iv_rank_cboe
                    iv_data = get_iv_rank_cboe(symbol, current_price)
                    if iv_data:
                        iv_rank = iv_data["iv_rank"]
                except Exception:
                    pass

            iv_cheap  = iv_rank is not None and iv_rank < 30
            iv_rich   = iv_rank is not None and iv_rank > 60
            high_conv = score is not None and score >= 7.5

            if iv_rich:
                best = "Cash-Secured Put or Iron Condor (sell premium — IV expensive)"
            elif iv_cheap and high_conv:
                best = "Long Call" if direction == "LONG" else "Long Put"
            elif iv_cheap:
                best = "Long Straddle (cheap IV + uncertain direction)"
            else:
                best = "Long Call" if direction == "LONG" else "Long Put"

            iv_txt = f"IV rank {iv_rank:.0f} ({'cheap' if iv_cheap else 'rich' if iv_rich else 'normal'})" if iv_rank is not None else "IV rank unknown"
            dir_txt = "Bullish" if direction == "LONG" else "Bearish"
            summary = f"{dir_txt} signal | {iv_txt} | {'High conviction → buy premium' if high_conv else 'Moderate → consider spreads'} | source: CBOE ✅"

            return {
                "ticker": symbol, "price": current_price, "iv_rank": iv_rank,
                "direction": direction, "best_strategy": best, "summary": summary,
                "directional": [c for c in directional if c],
                "neutral":     [c for c in neutral if c],
                "income":      [c for c in income if c],
                "all":         [c for c in (directional + neutral + income) if c],
            }

        # ── CBOE unavailable — fall back to yfinance ──
        tk = yf.Ticker(symbol)

        # Get expirations
        exps = _get_expirations(tk, min_days=5, max_days=60)
        if not exps:
            exps = _get_expirations(tk, min_days=2, max_days=90)
        if not exps:
            return {"ticker": symbol, "error": "no options available"}

        # Pick expiry windows
        short_exp = exps[0]                          # ~1-2 weeks
        mid_exp   = exps[len(exps)//2] if len(exps)>1 else exps[-1]  # ~3 weeks
        long_exp  = exps[-1]                         # ~4-6 weeks

        # IV regime
        iv_cheap = iv_rank is not None and iv_rank < 30
        iv_rich  = iv_rank is not None and iv_rank > 60
        high_conv = score is not None and score >= 7.5

        # ── Build strategy buckets ──

        directional = []
        neutral     = []
        income      = []

        # ─ DIRECTIONAL ─
        if direction == "LONG":
            # Best call for conviction plays
            c = _long_call(tk, *short_exp, current_price, "🥇 BEST CALL (ATM)")
            if c: directional.append(c)
            # Swing call
            c2 = _long_call(tk, *long_exp, current_price * 1.04, "🎰 SWING CALL (OTM)")
            if c2: c2["label"] = "🎰 SWING CALL (OTM)"; directional.append(c2)
            # Spread if IV is rich (cheaper)
            c3 = _bull_call_spread(tk, *mid_exp, current_price, "📈 BULL CALL SPREAD")
            if c3: directional.append(c3)
        else:  # SHORT
            c = _long_put(tk, *short_exp, current_price, "🥇 BEST PUT (ATM)")
            if c: directional.append(c)
            c2 = _long_put(tk, *long_exp, current_price * 0.96, "🎰 SWING PUT (OTM)")
            if c2: c2["label"] = "🎰 SWING PUT (OTM)"; directional.append(c2)
            c3 = _bear_put_spread(tk, *mid_exp, current_price, "📉 BEAR PUT SPREAD")
            if c3: directional.append(c3)

        # ─ NEUTRAL / VOL ─
        straddle = _long_straddle(tk, *mid_exp, current_price, "⚡ LONG STRADDLE")
        if straddle: neutral.append(straddle)
        # Short straddle opposite: only if IV very rich
        ic = _iron_condor(tk, *long_exp, current_price, "🦅 IRON CONDOR")
        if ic:
            ic["note"] = "Best when price consolidating. " + ic.get("note","")
            neutral.append(ic)

        # ─ INCOME ─
        if has_position or direction == "LONG":
            cc = _covered_call(tk, *mid_exp, current_price, "📤 COVERED CALL")
            if cc: income.append(cc)
        csp = _cash_secured_put(tk, *short_exp, current_price, "💰 CASH-SECURED PUT")
        if csp: income.append(csp)

        # ── Pick best strategy based on regime ──
        if iv_rich:
            best = "Iron Condor or Cash-Secured Put (sell premium while IV is expensive)"
        elif iv_cheap and high_conv:
            best = "Long Call" if direction == "LONG" else "Long Put"
        elif iv_cheap and not high_conv:
            best = "Long Straddle (cheap IV + uncertain direction)"
        elif high_conv:
            best = "Bull Call Spread" if direction == "LONG" else "Bear Put Spread"
        else:
            best = "Long Call Spread" if direction == "LONG" else "Bear Put Spread"

        # ── Summary text ──
        iv_txt = f"IV rank {iv_rank:.0f} ({'cheap' if iv_cheap else 'rich' if iv_rich else 'normal'})" if iv_rank is not None else "IV rank unknown"
        dir_txt = "Bullish" if direction == "LONG" else "Bearish"
        summary = (
            f"{dir_txt} signal | {iv_txt} | "
            f"{'High conviction → buy premium aggressively' if high_conv else 'Moderate conviction → consider spreads'}"
        )

        return {
            "ticker": symbol,
            "price": current_price,
            "iv_rank": iv_rank,
            "direction": direction,
            "best_strategy": best,
            "directional": [c for c in directional if c],
            "neutral":     [c for c in neutral if c],
            "income":      [c for c in income if c],
            "all":         [c for c in (directional + neutral + income) if c],
            "summary": summary,
        }

    except Exception as e:
        return {"ticker": symbol, "error": str(e)}


# ── LEGACY COMPATIBILITY ──────────────────────────────────────────────────────

def get_options_contracts(
    symbol: str,
    direction: str = "LONG",
    current_price: Optional[float] = None,
    num_contracts: int = 3,
) -> list:
    """
    Legacy function — returns flat list of top contracts.
    Used by Discord signal cards (backward compatible).
    """
    result = get_options_strategies(symbol, direction, current_price)
    return result.get("all", [])[:num_contracts]


# ── DISCORD FORMATTER ─────────────────────────────────────────────────────────

def format_options_block(result: dict, discord: bool = True) -> str:
    """
    Format multi-strategy options block.
    discord=True → compact single-message format (fits 2000 char Discord limit)
    discord=False → full verbose format for dashboard/logs
    """
    if result.get("error"):
        return ""

    ticker   = result["ticker"]
    price    = result.get("price", 0)
    best     = result.get("best_strategy", "")
    summary  = result.get("summary", "")
    dir_txt  = "📈 BULLISH" if result.get("direction") == "LONG" else "📉 BEARISH"

    def _fmt(c) -> str:
        tp  = f"${c['tp']}"  if c.get("tp")  and c["tp"] != 0 else "—"
        sl  = f"${c['sl']}"  if c.get("sl")  and c["sl"] != 0 else "—"
        rr  = f"{c['rr']}:1" if c.get("rr") else "—"
        ml  = f"${c['max_loss']}" if c.get("max_loss") else "—"
        mp  = str(c.get("max_profit","—"))[:30]
        iv  = f"IV {c['iv']}%" if c.get("iv") else ""
        be  = ""
        if c.get("breakeven_up"):
            be = f"BE ↑${c['breakeven_up']} ↓${c['breakeven_dn']}"
        note = f"\n     ℹ {c['note'][:80]}" if c.get("note") and not discord else ""
        return (
            f"  {c['label']}  {c['strategy']} — {c['type']} Exp {c.get('expiry_fmt','')} ({c.get('days_to_exp','?')}d)\n"
            f"     Entry ${c['entry']:.2f} | SL {sl} | TP {tp} | R/R {rr} | {iv}\n"
            f"     Max loss {ml} | Max profit: {mp}"
            + (f"\n     {be}" if be else "")
            + note
        )

    lines = ["```"]
    lines.append(f"📋 OPTIONS STRATEGIES — {ticker} @ ${price:.2f}  {dir_txt}")
    if best:
        lines.append(f"★ Recommended: {best}")
    if summary and not discord:
        lines.append(f"  {summary}")
    lines.append("─" * 48)

    dirs = result.get("directional", [])
    neus = result.get("neutral", [])
    incs = result.get("income", [])

    if dirs:
        lines.append("\n📈 DIRECTIONAL")
        for c in dirs[:3]: lines.append(_fmt(c))

    if neus:
        lines.append("\n⚖️  NEUTRAL / VOL")
        for c in neus[:2]: lines.append(_fmt(c))

    if incs:
        lines.append("\n💰 INCOME")
        for c in incs[:2]: lines.append(_fmt(c))

    lines.append("```")
    block = "\n".join(lines)

    # Discord 2000-char safety: truncate income section if too long
    if discord and len(block) > 1800:
        lines2 = ["```"]
        lines2.append(f"📋 OPTIONS — {ticker}  {dir_txt}")
        if best:
            lines2.append(f"★ {best}")
        lines2.append("─" * 40)
        if dirs:
            lines2.append("📈 DIRECTIONAL")
            for c in dirs[:2]: lines2.append(_fmt(c))
        if neus:
            lines2.append("\n⚖️  NEUTRAL")
            lines2.append(_fmt(neus[0]))
        if incs:
            lines2.append("\n💰 INCOME")
            lines2.append(_fmt(incs[0]))
        lines2.append("```")
        block = "\n".join(lines2)

    return block


def format_options_section(contracts: list, direction: str = "LONG") -> str:
    """Legacy formatter — still used by discord_signal_card.py."""
    if not contracts:
        return ""
    opt_type = "CALLS" if direction == "LONG" else "PUTS"
    ticker = contracts[0].get("ticker", "") if contracts else ""
    lines = ["```", f"📋 OPTIONS — {ticker} {opt_type}", "─" * 42]
    for c in contracts:
        lines.append(f"{c['label']}  {c['ticker']} {c['type']} ${c['strike']:g} Exp {c.get('expiry_fmt','')}")
        sl = f"${c['sl']}" if c.get("sl") else "n/a"
        tp = f"${c['tp']}" if c.get("tp") else "n/a"
        lines.append(f"  Entry ${c['entry']:.2f} | SL {sl} | TP {tp} | R/R {c.get('rr','--')}:1")
        if c.get("volume") or c.get("oi"):
            lines.append(f"  Vol {c.get('volume',0):,} | OI {c.get('oi',0):,} | IV {c.get('iv','--')}%")
        lines.append("")
    lines.append("```")
    return "\n".join(lines)
