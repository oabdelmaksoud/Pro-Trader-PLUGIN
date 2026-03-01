#!/usr/bin/env python3
"""
quick_quote.py — Fast live quote for 1–5 tickers. Used by private channel responses.

Usage:
  python3 scripts/quick_quote.py NVDA
  python3 scripts/quick_quote.py NVDA MSFT AAPL
"""
import sys
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

import yfinance as yf


def get_quote(ticker: str) -> dict:
    """Get live quote with key metrics."""
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        hist = t.history(period="2d", interval="1d")

        price = info.last_price or 0
        prev_close = info.previous_close or price
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        volume = info.three_month_average_volume or 0

        # 52-week range
        week52_high = getattr(info, 'year_high', None)
        week52_low = getattr(info, 'year_low', None)

        # Try to get more info
        try:
            full_info = t.info
            market_cap = full_info.get('marketCap', 0)
            pe_ratio = full_info.get('trailingPE', None)
            eps = full_info.get('trailingEps', None)
            name = full_info.get('shortName', ticker)
            sector = full_info.get('sector', 'Unknown')
        except Exception:
            market_cap = 0
            pe_ratio = None
            eps = None
            name = ticker
            sector = 'Unknown'

        return {
            'ticker': ticker.upper(),
            'name': name,
            'price': round(price, 2),
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
            'volume': volume,
            'week52_high': week52_high,
            'week52_low': week52_low,
            'market_cap': market_cap,
            'pe_ratio': round(pe_ratio, 1) if pe_ratio else None,
            'eps': round(eps, 2) if eps else None,
            'sector': sector,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M ET'),
            'error': None
        }
    except Exception as e:
        return {
            'ticker': ticker.upper(),
            'price': None,
            'error': str(e),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M ET')
        }


def format_quote(q: dict) -> str:
    if q.get('error'):
        return f"❌ {q['ticker']}: Could not fetch live data ({q['error']})"

    arrow = "🟢 ▲" if q['change_pct'] >= 0 else "🔴 ▼"
    sign = "+" if q['change'] >= 0 else ""

    mc = ""
    if q.get('market_cap') and q['market_cap'] > 0:
        mc_b = q['market_cap'] / 1e9
        mc = f" | Mkt Cap: ${mc_b:.0f}B"

    pe = f" | P/E: {q['pe_ratio']}" if q.get('pe_ratio') else ""
    r52 = ""
    if q.get('week52_high') and q.get('week52_low'):
        r52 = f" | 52W: ${q['week52_low']:.2f}–${q['week52_high']:.2f}"

    return (
        f"**{q['ticker']}** ({q['name']})\n"
        f"{arrow} ${q['price']:.2f} ({sign}{q['change_pct']:.2f}%)\n"
        f"Sector: {q['sector']}{mc}{pe}{r52}\n"
        f"*Live as of {q['timestamp']}*"
    )


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["SPY"]
    for ticker in tickers[:5]:  # max 5
        q = get_quote(ticker.upper())
        print(format_quote(q))
        print()
