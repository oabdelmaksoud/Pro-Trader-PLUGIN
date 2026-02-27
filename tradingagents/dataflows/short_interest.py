"""
CooperCorp PRJ-002 — Short interest data.
Uses finviz (scrape) and iborrowdesk (public API). No key needed.
"""
import requests
import re
from typing import Optional


def get_finviz_short_interest(sym: str) -> dict:
    """Scrape short interest data from Finviz."""
    try:
        url = f"https://finviz.com/quote.ashx?t={sym}"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        html = r.text

        def extract(pattern):
            m = re.search(pattern, html)
            return m.group(1) if m else None

        short_float = extract(r'"Short Float"[^>]*>\s*<[^>]*>([^<]+)<')
        if not short_float:
            short_float = extract(r'>Short Float</td>[^<]*<td[^>]*>([^<]+)<')
        if not short_float:
            short_float = extract(r'shortFloat["\s:]+([0-9.]+%?)')
        short_ratio = extract(r'"Short Ratio"[^>]*>\s*<[^>]*>([^<]+)<')
        if not short_ratio:
            short_ratio = extract(r'>Short Ratio</td>[^<]*<td[^>]*>([^<]+)<')
        inst_own = extract(r'"Inst Own"[^>]*>\s*<[^>]*>([^<]+)<')
        float_shares = extract(r'"Shs Float"[^>]*>\s*<[^>]*>([^<]+)<')

        return {
            "symbol": sym,
            "short_float": short_float,   # e.g. "2.31%"
            "short_ratio": short_ratio,   # days to cover
            "institutional_ownership": inst_own,
            "float": float_shares,
            "squeeze_potential": _assess_squeeze(short_float, short_ratio),
        }
    except Exception as e:
        return {"error": str(e)}


def _assess_squeeze(short_float: Optional[str], short_ratio: Optional[str]) -> str:
    """Assess short squeeze potential."""
    try:
        sf = float(short_float.replace("%", "")) if short_float and "%" in short_float else 0
        sr = float(short_ratio) if short_ratio else 0
        if sf > 20 and sr > 5:
            return "HIGH — prime squeeze candidate"
        elif sf > 10 or sr > 3:
            return "MODERATE — watch for momentum"
        else:
            return "LOW"
    except Exception:
        return "UNKNOWN"


def get_iborrowdesk_rate(sym: str) -> dict:
    """Get borrow rate from iborrowdesk (high rate = hard to borrow = squeeze risk)."""
    try:
        r = requests.get(
            f"https://iborrowdesk.com/api/ticker/{sym}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8
        )
        data = r.json()
        if isinstance(data, list) and data:
            latest = data[0]
            rate = latest.get("rate", 0)
            available = latest.get("available", 0)
            return {
                "symbol": sym,
                "borrow_rate_pct": rate,
                "shares_available": available,
                "hard_to_borrow": rate > 10,
                "note": "High rate + low availability = squeeze risk" if rate > 10 else "Normal borrow conditions",
            }
        return {"symbol": sym, "note": "No data from iborrowdesk"}
    except Exception as e:
        return {"error": str(e)}


def get_short_data(sym: str) -> dict:
    """Combined short interest summary."""
    finviz = get_finviz_short_interest(sym)
    iborrow = get_iborrowdesk_rate(sym)
    return {
        "symbol": sym,
        "finviz": finviz,
        "iborrowdesk": iborrow,
        "squeeze_potential": finviz.get("squeeze_potential", "UNKNOWN"),
    }
