"""
CooperCorp PRJ-002 — Options Chain Scanner
Suggests 2-3 optimal contract strikes/expirations for a signal.
Uses yfinance options data (free, no key needed).

Contract selection logic:
  LONG signal → CALL options
  SHORT signal → PUT options

3 contracts suggested:
  1. BEST — Near ATM (1-2 weeks out, delta ~0.40-0.50)
  2. ALT  — Slightly OTM (2-3 weeks out, delta ~0.30)
  3. SWING — Further OTM (3-5 weeks out, delta ~0.20-0.25)

Premium pricing:
  Entry = mid price (bid+ask)/2
  SL    = entry × 0.75 (lose 25% of premium)
  TP    = entry × 1.80 (gain 80%, ~2:1+ R/R)
"""
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional


def get_options_contracts(
    symbol: str,
    direction: str = "LONG",
    current_price: Optional[float] = None,
    num_contracts: int = 3,
) -> list:
    """
    Suggest optimal options contracts for a signal.

    Args:
        symbol: Ticker (e.g. 'NVDA')
        direction: 'LONG' → CALLs, 'SHORT' → PUTs
        current_price: override current price
        num_contracts: how many contracts to suggest (default 3)

    Returns:
        List of contract dicts with symbol, strike, expiry, entry, sl, tp, delta, label
    """
    try:
        tk = yf.Ticker(symbol)

        # Get current price
        if not current_price:
            info = tk.fast_info
            current_price = float(info.last_price or info.regular_market_price or 0)
            if not current_price:
                hist = tk.history(period="1d", interval="1m")
                current_price = float(hist["Close"].iloc[-1]) if not hist.empty else 0

        if not current_price:
            return []

        # Get available expiry dates
        expirations = tk.options
        if not expirations:
            return []

        # Filter to expirations 5-45 days out
        today = datetime.today()
        valid_exps = []
        for exp in expirations:
            exp_dt = datetime.strptime(exp, "%Y-%m-%d")
            days = (exp_dt - today).days
            if 5 <= days <= 45:
                valid_exps.append((exp, days, exp_dt))

        if not valid_exps:
            # Widen range if no weeklies
            for exp in expirations:
                exp_dt = datetime.strptime(exp, "%Y-%m-%d")
                days = (exp_dt - today).days
                if 2 <= days <= 60:
                    valid_exps.append((exp, days, exp_dt))

        if not valid_exps:
            return []

        # Sort by days
        valid_exps.sort(key=lambda x: x[1])

        # Select 3 expiry windows
        exp_targets = []
        if len(valid_exps) >= 1:
            exp_targets.append(valid_exps[0])  # shortest
        if len(valid_exps) >= 2:
            mid_idx = len(valid_exps) // 2
            if valid_exps[mid_idx] != valid_exps[0]:
                exp_targets.append(valid_exps[mid_idx])
        if len(valid_exps) >= 3:
            if valid_exps[-1] not in exp_targets:
                exp_targets.append(valid_exps[-1])

        # Strike multipliers for CALL vs PUT
        # LONG (CALLs): near-ATM, slight OTM, further OTM
        # SHORT (PUTs): near-ATM, slight OTM, further OTM
        if direction == "LONG":
            opt_type = "calls"
            strike_mults = [1.01, 1.04, 1.08]  # near-ATM → OTM
        else:
            opt_type = "puts"
            strike_mults = [0.99, 0.96, 0.92]  # near-ATM → OTM

        labels = ["🥇 BEST", "🥈 ALT", "🎰 SWING"]
        results = []

        for i, (exp_str, days, exp_dt) in enumerate(exp_targets[:num_contracts]):
            mult = strike_mults[i] if i < len(strike_mults) else strike_mults[-1]
            target_strike = current_price * mult

            try:
                chain = tk.option_chain(exp_str)
                options = chain.calls if opt_type == "calls" else chain.puts

                if options.empty:
                    continue

                # Find closest strike
                options = options.copy()
                options["strike_diff"] = abs(options["strike"] - target_strike)
                best = options.nsmallest(1, "strike_diff").iloc[0]

                strike = float(best["strike"])
                bid = float(best.get("bid", 0) or 0)
                ask = float(best.get("ask", 0) or 0)
                last = float(best.get("lastPrice", 0) or 0)
                delta = float(best.get("delta", 0) or 0) if "delta" in best else None
                volume = int(best.get("volume", 0) or 0)
                oi = int(best.get("openInterest", 0) or 0)
                iv = float(best.get("impliedVolatility", 0) or 0)

                # Entry = mid price, or last if mid not available
                if bid > 0 and ask > 0:
                    entry = round((bid + ask) / 2, 2)
                elif last > 0:
                    entry = round(last, 2)
                else:
                    continue

                if entry < 0.05:
                    continue  # Too cheap / illiquid

                sl = round(entry * 0.75, 2)
                tp = round(entry * 1.80, 2)
                rr = round((tp - entry) / (entry - sl), 1)

                # Format expiry as MM/DD
                exp_formatted = exp_dt.strftime("%-m/%-d")

                contract_sym = f"{symbol.upper()} {'Call' if opt_type == 'calls' else 'Put'} ${strike:g} Exp {exp_formatted}"

                results.append({
                    "label": labels[i] if i < len(labels) else f"#{i+1}",
                    "symbol": contract_sym,
                    "ticker": symbol.upper(),
                    "type": "Call" if opt_type == "calls" else "Put",
                    "strike": strike,
                    "expiry": exp_str,
                    "expiry_fmt": exp_formatted,
                    "days_to_exp": days,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "rr": rr,
                    "bid": bid,
                    "ask": ask,
                    "delta": abs(delta) if delta else None,
                    "volume": volume,
                    "open_interest": oi,
                    "iv": round(iv * 100, 1) if iv else None,
                    "contract_size": 100,  # standard
                    "max_loss_per_contract": round(entry * 100, 2),
                })

            except Exception as e:
                continue

        return results

    except Exception as e:
        return []


def format_options_section(contracts: list, direction: str = "LONG") -> str:
    """Format options contracts into Discord-ready text."""
    if not contracts:
        return ""

    opt_type = "CALLS" if direction == "LONG" else "PUTS"
    ticker = contracts[0]["ticker"] if contracts else ""

    lines = [f"```", f"📋 OPTIONS — {ticker} {opt_type}"]
    lines.append("─" * 42)

    for c in contracts:
        delta_str = f" | Δ{c['delta']:.2f}" if c.get("delta") else ""
        iv_str = f" | IV {c['iv']}%" if c.get("iv") else ""
        vol_str = f" | Vol {c['volume']:,}" if c.get("volume") else ""

        lines.append(f"{c['label']}  {c['ticker']} {c['type']} ${c['strike']:g} Exp {c['expiry_fmt']}")
        lines.append(f"  Entry ${c['entry']:.2f} | SL ${c['sl']:.2f} | TP ${c['tp']:.2f} | R/R {c['rr']}:1")
        lines.append(f"  Cost: ${c['max_loss_per_contract']:.0f}/contract{delta_str}{iv_str}")
        if c.get("volume") or c.get("open_interest"):
            lines.append(f"  Liq: Vol {c.get('volume',0):,} | OI {c.get('open_interest',0):,}")
        lines.append("")

    lines.append("```")
    return "\n".join(lines)
