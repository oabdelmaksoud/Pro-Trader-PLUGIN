"""
CooperCorp PRJ-002 — Stocktwits Sentiment Integration
Public API — no API key required. Returns retail trader sentiment.
"""
import requests
from datetime import datetime, timezone

STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"


def get_symbol_sentiment(symbol: str, limit: int = 30) -> dict:
    """
    Get recent Stocktwits messages and sentiment for a symbol.
    No API key required — public endpoint.
    Returns: {symbol, bull_count, bear_count, sentiment, messages, sentiment_pct}
    """
    try:
        url = f"{STOCKTWITS_BASE}/streams/symbol/{symbol.upper()}.json"
        params = {"limit": limit}
        headers = {"User-Agent": "CooperCorpTrading/1.0"}

        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"symbol": symbol, "error": f"HTTP {resp.status_code}", "sentiment": "neutral"}

        data = resp.json()
        messages = data.get("messages", [])

        bull_count = 0
        bear_count = 0
        neutral_count = 0
        sample_messages = []

        for msg in messages:
            entities = msg.get("entities", {})
            sentiment_data = entities.get("sentiment", {})
            basic = sentiment_data.get("basic", "Neutral") if sentiment_data else "Neutral"

            if basic == "Bullish":
                bull_count += 1
            elif basic == "Bearish":
                bear_count += 1
            else:
                neutral_count += 1

            body = msg.get("body", "")[:100]
            user = msg.get("user", {}).get("username", "anon")
            created = msg.get("created_at", "")

            if len(sample_messages) < 5:
                sample_messages.append(f"@{user} [{basic}]: {body}")

        total = bull_count + bear_count + neutral_count
        if total == 0:
            return {"symbol": symbol, "sentiment": "neutral", "total": 0}

        bull_pct = round(bull_count / total * 100, 1)
        bear_pct = round(bear_count / total * 100, 1)
        overall = "bullish" if bull_pct > 55 else "bearish" if bear_pct > 55 else "neutral"

        return {
            "symbol": symbol,
            "source": "stocktwits",
            "total_messages": total,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "neutral_count": neutral_count,
            "bull_pct": bull_pct,
            "bear_pct": bear_pct,
            "overall_sentiment": overall,
            "sample_messages": sample_messages,
        }
    except Exception as e:
        return {"symbol": symbol, "source": "stocktwits", "error": str(e), "sentiment": "neutral"}


def format_for_analyst(symbol: str) -> str:
    """Returns Stocktwits sentiment formatted for LLM consumption."""
    data = get_symbol_sentiment(symbol)

    if "error" in data:
        return f"Stocktwits unavailable for {symbol}: {data['error']}"

    if data.get("total_messages", 0) == 0:
        return f"No Stocktwits activity for {symbol}."

    msgs_text = "\n".join([f"  {m}" for m in data.get("sample_messages", [])])

    return f"""Stocktwits Sentiment for ${symbol}:
Total messages: {data['total_messages']} | 🟢 Bullish: {data['bull_pct']}% | 🔴 Bearish: {data['bear_pct']}%
Overall: {data['overall_sentiment'].upper()}

Recent messages:
{msgs_text}"""


def is_available() -> bool:
    """Stocktwits public API requires no key."""
    try:
        resp = requests.get(f"{STOCKTWITS_BASE}/streams/symbol/AAPL.json", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False
