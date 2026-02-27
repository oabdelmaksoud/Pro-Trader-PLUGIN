"""
CooperCorp PRJ-002 — Earnings Whisper numbers.
Free scrape from earningswhispers.com. No API key needed.
Whisper > consensus = already priced in = higher bar to beat.
"""
import requests
import re


def get_whisper_number(sym: str) -> dict:
    """Fetch EarningsWhisper number for upcoming earnings."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.earningswhispers.com/",
        }
        url = f"https://www.earningswhispers.com/stocks/{sym.lower()}"
        r = requests.get(url, headers=headers, timeout=10)
        html = r.text

        # Extract whisper EPS
        whisper = None
        consensus = None
        date_str = None

        m = re.search(r'whisper[^"]*"[^"]*"\s*>\s*([-\d.]+)', html, re.IGNORECASE)
        if m:
            whisper = float(m.group(1))

        m2 = re.search(r'consensus[^"]*"[^"]*"\s*>\s*([-\d.]+)', html, re.IGNORECASE)
        if m2:
            consensus = float(m2.group(1))

        m3 = re.search(r'(\w+ \d+, \d{4})', html)
        if m3:
            date_str = m3.group(1)

        if whisper is None and consensus is None:
            return {"symbol": sym, "note": "No earnings data found or not near earnings"}

        spread = None
        bar_higher = False
        if whisper is not None and consensus is not None and consensus != 0:
            spread = round((whisper - consensus) / abs(consensus) * 100, 1)
            bar_higher = spread > 5  # whisper >5% above consensus = bar set higher

        return {
            "symbol": sym,
            "whisper_eps": whisper,
            "consensus_eps": consensus,
            "spread_pct": spread,
            "earnings_date": date_str,
            "bar_higher_than_consensus": bar_higher,
            "note": f"Whisper ${whisper} vs consensus ${consensus} ({spread:+.1f}%). {'⚠️ Bar set high' if bar_higher else '✅ Normal expectations'}" if whisper and consensus and spread is not None else "Data unavailable",
        }
    except Exception as e:
        return {"symbol": sym, "error": str(e)}
