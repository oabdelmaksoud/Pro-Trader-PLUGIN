"""
CooperCorp PRJ-002 — Micro Futures Data Module
Provides contract specs, margin requirements, real-time data, and scoring adjustments
for micro/mini futures contracts tradeable on a $500 recovery account.

Supported contracts (from broker screenshot, Mar 2026):
  /METH26   Micro Ether         $77    margin
  /MCDH26   Micro CAD           $110   margin
  /M6AH26   Micro AUD           $209   margin
  /M6BH26   Micro GBP           $220   margin
  /M6EH26   Micro EUR           $297   margin
  /BFFH2613 Bitcoin Friday      $365   margin
  /1OZJ26   1-Ounce Gold        $472   margin
  /MSFH26   Micro Swiss Franc   $495   margin
  /MNGJ26   Micro Nat Gas       $633   margin

Data sources: yfinance (CME futures via =F symbols), realtime_quotes proxy layer.
"""
import os
import re
from datetime import datetime, timezone
from typing import Optional

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False


# ── Contract Specifications ──────────────────────────────────────────────────
# Each contract: symbol root, yfinance symbol, point value, tick size, tick value,
#                exchange, asset class, margin estimate (from broker screenshot)

MICRO_FUTURES = {
    # ── Crypto Futures ──
    "MET": {
        "name": "Micro Ether Futures",
        "yf_symbol": "ETH=F",
        "exchange": "CME",
        "asset_class": "crypto",
        "point_value": 0.1,  # 0.1 ETH
        "tick_size": 0.25,
        "tick_value": 0.025,
        "margin": 77,
        "proxy_etf": "ETH-USD",
        "contract_months": "HMUZ",  # Mar, Jun, Sep, Dec
    },
    "BFF": {
        "name": "Bitcoin Friday Futures",
        "yf_symbol": "BTC=F",
        "exchange": "CME",
        "asset_class": "crypto",
        "point_value": 0.01,  # 0.01 BTC
        "tick_size": 5.0,
        "tick_value": 0.05,
        "margin": 365,
        "proxy_etf": "BTC-USD",
        "contract_months": "weekly",  # weekly Friday expiry
    },
    # ── FX Micro Futures ──
    "MCD": {
        "name": "Micro Canadian Dollar Futures",
        "yf_symbol": "CAD=X",
        "exchange": "CME",
        "asset_class": "fx",
        "point_value": 10000,  # C$10,000
        "tick_size": 0.00005,
        "tick_value": 0.50,
        "margin": 110,
        "proxy_etf": "FXC",
        "contract_months": "HMUZ",
    },
    "M6A": {
        "name": "Micro Australian Dollar Futures",
        "yf_symbol": "AUD=X",
        "exchange": "CME",
        "asset_class": "fx",
        "point_value": 10000,  # A$10,000
        "tick_size": 0.00005,
        "tick_value": 0.50,
        "margin": 209,
        "proxy_etf": "FXA",
        "contract_months": "HMUZ",
    },
    "M6B": {
        "name": "Micro British Pound Futures",
        "yf_symbol": "GBP=X",
        "exchange": "CME",
        "asset_class": "fx",
        "point_value": 6250,  # £6,250
        "tick_size": 0.0001,
        "tick_value": 0.625,
        "margin": 220,
        "proxy_etf": "FXB",
        "contract_months": "HMUZ",
    },
    "M6E": {
        "name": "Micro Euro Futures",
        "yf_symbol": "EUR=X",
        "exchange": "CME",
        "asset_class": "fx",
        "point_value": 12500,  # €12,500
        "tick_size": 0.00005,
        "tick_value": 0.625,
        "margin": 297,
        "proxy_etf": "FXE",
        "contract_months": "HMUZ",
    },
    "MSF": {
        "name": "Micro Swiss Franc Futures",
        "yf_symbol": "CHF=X",
        "exchange": "CME",
        "asset_class": "fx",
        "point_value": 12500,  # CHF 12,500
        "tick_size": 0.0001,
        "tick_value": 1.25,
        "margin": 495,
        "proxy_etf": None,
        "contract_months": "HMUZ",
    },
    # ── Commodity Micro Futures ──
    "1OZ": {
        "name": "1-Ounce Gold Futures",
        "yf_symbol": "GC=F",
        "exchange": "CME",
        "asset_class": "commodity",
        "point_value": 1,  # 1 troy oz
        "tick_size": 0.10,
        "tick_value": 0.10,
        "margin": 472,
        "proxy_etf": "GLD",
        "contract_months": "GJMQVZ",
    },
    "MNG": {
        "name": "Micro Natural Gas Futures",
        "yf_symbol": "NG=F",
        "exchange": "CME",
        "asset_class": "commodity",
        "point_value": 1000,  # 1,000 MMBtu
        "tick_size": 0.001,
        "tick_value": 1.00,
        "margin": 633,
        "proxy_etf": "UNG",
        "contract_months": "all",
    },
    # ── Equity Index Micro Futures (common, higher margin) ──
    "MES": {
        "name": "Micro E-mini S&P 500",
        "yf_symbol": "ES=F",
        "exchange": "CME",
        "asset_class": "index",
        "point_value": 5,  # $5 per point
        "tick_size": 0.25,
        "tick_value": 1.25,
        "margin": 1500,  # typical, varies
        "proxy_etf": "SPY",
        "contract_months": "HMUZ",
    },
    "MNQ": {
        "name": "Micro E-mini Nasdaq-100",
        "yf_symbol": "NQ=F",
        "exchange": "CME",
        "asset_class": "index",
        "point_value": 2,  # $2 per point
        "tick_size": 0.25,
        "tick_value": 0.50,
        "margin": 2000,  # typical, varies
        "proxy_etf": "QQQ",
        "contract_months": "HMUZ",
    },
    "MYM": {
        "name": "Micro E-mini Dow",
        "yf_symbol": "YM=F",
        "exchange": "CME",
        "asset_class": "index",
        "point_value": 0.50,  # $0.50 per point
        "tick_size": 1.0,
        "tick_value": 0.50,
        "margin": 1000,
        "proxy_etf": "DIA",
        "contract_months": "HMUZ",
    },
    "MCL": {
        "name": "Micro WTI Crude Oil",
        "yf_symbol": "CL=F",
        "exchange": "CME",
        "asset_class": "commodity",
        "point_value": 100,  # 100 barrels
        "tick_size": 0.01,
        "tick_value": 1.00,
        "margin": 800,
        "proxy_etf": "USO",
        "contract_months": "all",
    },
}

# Margin tiers for $500 account
MARGIN_TIER_LOW = 300    # Can trade with $500 account (50%+ margin buffer)
MARGIN_TIER_MED = 500    # Tight but tradeable
MARGIN_TIER_HIGH = 1000  # Needs at least $1,000 account


def parse_futures_symbol(symbol: str) -> Optional[dict]:
    """
    Parse a futures symbol like /METH26, /M6AH26, /BFFH2613 into components.
    Returns: {root, month_code, year, contract_spec} or None if not a futures symbol.
    """
    # Strip leading /
    sym = symbol.lstrip("/").upper()

    # Try matching each known root
    for root, spec in MICRO_FUTURES.items():
        if sym.startswith(root):
            remainder = sym[len(root):]
            # Month code is first char after root (H=Mar, M=Jun, U=Sep, Z=Dec, etc.)
            if remainder:
                month_code = remainder[0]
                year_part = remainder[1:]
                return {
                    "root": root,
                    "month_code": month_code,
                    "year_suffix": year_part,
                    "spec": spec,
                    "original": symbol,
                }
    return None


def is_futures_symbol(symbol: str) -> bool:
    """Check if a symbol looks like a futures contract."""
    sym = symbol.strip()
    if sym.startswith("/"):
        return True
    # Also match =F suffix (yfinance format)
    if sym.endswith("=F") or sym.endswith("=X"):
        return True
    # Check if it matches a known root
    return parse_futures_symbol(sym) is not None


def get_contract_spec(symbol: str) -> Optional[dict]:
    """Get the contract specification for a futures symbol."""
    parsed = parse_futures_symbol(symbol)
    if parsed:
        return parsed["spec"]
    # Direct lookup by root
    root = symbol.lstrip("/").upper()
    return MICRO_FUTURES.get(root)


def get_affordable_contracts(account_value: float = 500.0, margin_buffer: float = 1.5) -> list:
    """
    Return contracts affordable with given account value.
    margin_buffer: multiplier for safety (1.5 = need 50% more than min margin).
    """
    affordable = []
    for root, spec in MICRO_FUTURES.items():
        required = spec["margin"] * margin_buffer
        if account_value >= required:
            affordable.append({
                "root": root,
                "name": spec["name"],
                "margin": spec["margin"],
                "headroom_pct": round((account_value - spec["margin"]) / account_value * 100, 1),
                "asset_class": spec["asset_class"],
            })
    return sorted(affordable, key=lambda x: x["margin"])


def get_futures_quote(symbol: str) -> dict:
    """
    Fetch real-time data for a futures contract.
    Uses yfinance =F symbols as primary source.
    Falls back to proxy ETF via realtime_quotes.
    """
    spec = get_contract_spec(symbol)
    if not spec:
        return {"symbol": symbol, "error": "Unknown futures contract"}

    result = {
        "symbol": symbol,
        "name": spec["name"],
        "asset_class": spec["asset_class"],
        "margin": spec["margin"],
        "point_value": spec["point_value"],
        "tick_value": spec["tick_value"],
    }

    # Try yfinance first (direct CME data)
    if YF_AVAILABLE:
        try:
            yf_sym = spec["yf_symbol"]
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period="5d", interval="1h")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[0])
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0
                result.update({
                    "price": round(price, 4),
                    "prev_close": round(prev_close, 4),
                    "change": round(change, 4),
                    "change_pct": round(change_pct, 2),
                    "high_5d": round(float(hist["High"].max()), 4),
                    "low_5d": round(float(hist["Low"].min()), 4),
                    "volume": int(hist["Volume"].sum()),
                    "source": "yfinance_cme",
                })
                return result
        except Exception:
            pass

    # Fallback: use realtime_quotes proxy layer
    try:
        from tradingagents.dataflows.realtime_quotes import get_quote
        proxy_sym = spec.get("proxy_etf")
        if proxy_sym:
            q = get_quote(proxy_sym)
            if q and q.get("price"):
                result.update({
                    "price": q["price"],
                    "change_pct": q.get("change_pct", 0),
                    "source": f"proxy:{proxy_sym}",
                    "proxy_note": f"Price from {proxy_sym} ETF proxy",
                })
                return result
    except Exception:
        pass

    result["error"] = "No price data available"
    return result


def get_futures_technicals(symbol: str) -> dict:
    """
    Basic technical analysis for futures contract.
    Returns RSI, SMA, volume ratio — same shape as stock technicals.
    """
    spec = get_contract_spec(symbol)
    if not spec or not YF_AVAILABLE:
        return {"error": "Cannot fetch futures technicals"}

    try:
        yf_sym = spec["yf_symbol"]
        ticker = yf.Ticker(yf_sym)
        hist = ticker.history(period="1mo", interval="1d")
        if hist.empty or len(hist) < 14:
            return {"error": "Insufficient futures price history"}

        closes = hist["Close"]
        volumes = hist["Volume"]

        # RSI (14-period)
        delta = closes.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
        rsi = 100 - (100 / (1 + rs))

        # SMAs
        sma20 = closes.rolling(20).mean().iloc[-1] if len(closes) >= 20 else None
        sma50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
        price = closes.iloc[-1]

        # Volume ratio
        avg_vol = volumes.rolling(20).mean().iloc[-1] if len(volumes) >= 20 else volumes.mean()
        vol_ratio = volumes.iloc[-1] / avg_vol if avg_vol > 0 else 1.0

        # Price change
        prev = closes.iloc[-2] if len(closes) >= 2 else price
        change_pct = (price - prev) / prev * 100 if prev else 0

        return {
            "price": round(float(price), 4),
            "change_pct": round(float(change_pct), 2),
            "rsi": round(float(rsi), 1),
            "sma20": round(float(sma20), 4) if sma20 is not None else None,
            "sma50": round(float(sma50), 4) if sma50 is not None else None,
            "above_sma20": bool(price > sma20) if sma20 is not None else None,
            "above_sma50": bool(price > sma50) if sma50 is not None else None,
            "volume_ratio": round(float(vol_ratio), 2),
            "high_20d": round(float(closes.rolling(20).max().iloc[-1]), 4),
            "low_20d": round(float(closes.rolling(20).min().iloc[-1]), 4),
            "asset_type": "futures",
            "contract": spec["name"],
            "margin": spec["margin"],
            "source": "yfinance_cme",
        }
    except Exception as e:
        return {"error": f"Futures technicals failed: {e}"}


def get_session_hours(asset_class: str) -> dict:
    """Return trading session info for futures asset class."""
    sessions = {
        "index": {
            "globex": "Sun 6:00 PM – Fri 5:00 PM ET",
            "rth": "9:30 AM – 4:15 PM ET",
            "note": "Nearly 24h trading. Best liquidity during RTH.",
        },
        "fx": {
            "globex": "Sun 6:00 PM – Fri 5:00 PM ET",
            "rth": "8:00 AM – 5:00 PM ET",
            "note": "24h forex market. Overlap with London = best liquidity.",
        },
        "commodity": {
            "globex": "Sun 6:00 PM – Fri 5:00 PM ET",
            "rth": "9:30 AM – 2:30 PM ET (gold) / 9:00 AM – 2:30 PM ET (energy)",
            "note": "Energy and metals have different pit sessions.",
        },
        "crypto": {
            "globex": "Sun 6:00 PM – Fri 4:00 PM ET",
            "rth": "24/7 via spot, CME has breaks",
            "note": "CME crypto futures have maintenance breaks.",
        },
    }
    return sessions.get(asset_class, {"note": "Unknown session"})


def calculate_risk_per_trade(spec: dict, stop_ticks: int, account_value: float = 500.0) -> dict:
    """
    Calculate risk metrics for a futures trade.
    stop_ticks: number of ticks for stop loss.
    """
    tick_value = spec["tick_value"]
    risk_dollars = stop_ticks * tick_value
    risk_pct = (risk_dollars / account_value) * 100
    margin = spec["margin"]
    margin_pct = (margin / account_value) * 100

    return {
        "contract": spec["name"],
        "margin_required": margin,
        "margin_pct_of_account": round(margin_pct, 1),
        "stop_ticks": stop_ticks,
        "risk_dollars": round(risk_dollars, 2),
        "risk_pct_of_account": round(risk_pct, 2),
        "max_contracts": max(1, int(account_value * 0.02 / risk_dollars)) if risk_dollars > 0 else 0,
        "note": "1 contract max for recovery mode" if account_value < 1000 else "",
    }


def format_futures_context(symbol: str) -> str:
    """Format futures data for LLM agent consumption."""
    spec = get_contract_spec(symbol)
    if not spec:
        return f"Unknown futures contract: {symbol}"

    quote = get_futures_quote(symbol)
    technicals = get_futures_technicals(symbol)
    session = get_session_hours(spec["asset_class"])

    price_str = f"${quote.get('price', '?')}" if quote.get("price") else "unavailable"
    change_str = f"{quote.get('change_pct', 0):+.2f}%" if quote.get("change_pct") else ""

    tech_lines = []
    if not technicals.get("error"):
        tech_lines = [
            f"RSI: {technicals.get('rsi', '?')}",
            f"Above SMA20: {technicals.get('above_sma20', '?')}",
            f"Volume Ratio: {technicals.get('volume_ratio', '?')}x",
        ]

    return f"""Futures Contract: {spec['name']}
Asset Class: {spec['asset_class'].upper()} | Exchange: {spec['exchange']}
Price: {price_str} {change_str}
Margin: ${spec['margin']} | Point Value: ${spec['point_value']} | Tick Value: ${spec['tick_value']}
Session: {session.get('rth', 'N/A')}
{chr(10).join(tech_lines) if tech_lines else 'Technicals: unavailable'}"""


def is_available() -> bool:
    """Check if futures data fetching is available."""
    return YF_AVAILABLE
