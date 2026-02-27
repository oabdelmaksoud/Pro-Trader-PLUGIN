"""
CooperCorp PRJ-002 — Finnhub Data Integration
Free tier: 60 req/min. Provides: news, earnings, sentiment, company profile.
Get key at: https://finnhub.io
"""
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    import finnhub
    FINNHUB_AVAILABLE = True
except ImportError:
    FINNHUB_AVAILABLE = False

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")


def _get_client():
    if not FINNHUB_AVAILABLE:
        raise ImportError("finnhub-python not installed. Run: pip install finnhub-python")
    if not FINNHUB_KEY:
        raise ValueError("FINNHUB_API_KEY not set in environment")
    return finnhub.Client(api_key=FINNHUB_KEY)


def get_company_news(symbol: str, days_back: int = 7) -> str:
    """
    Get company-specific news from Finnhub (Bloomberg, Reuters, etc.)
    Returns formatted string for LLM consumption.
    """
    try:
        client = _get_client()
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_back)

        news = client.company_news(
            symbol.upper(),
            _from=start.strftime("%Y-%m-%d"),
            to=end.strftime("%Y-%m-%d")
        )

        if not news:
            return f"No recent news found for {symbol} via Finnhub."

        articles = []
        for item in news[:15]:  # Top 15 articles
            source = item.get("source", "Unknown")
            headline = item.get("headline", "")
            summary = item.get("summary", "")[:200]
            ts = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
            articles.append(f"[{ts.strftime('%Y-%m-%d %H:%M')}] {source}: {headline}\n  {summary}")

        return f"Finnhub News for {symbol} (last {days_back} days):\n\n" + "\n\n".join(articles)
    except Exception as e:
        return f"Finnhub news unavailable: {e}"


def get_market_news(category: str = "general", days_back: int = 2) -> str:
    """
    Get general market news. category: 'general', 'forex', 'crypto', 'merger'
    """
    try:
        client = _get_client()
        news = client.general_news(category, min_id=0)

        if not news:
            return "No general market news found via Finnhub."

        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        for item in news[:20]:
            ts = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
            if ts < cutoff:
                continue
            source = item.get("source", "Unknown")
            headline = item.get("headline", "")
            summary = item.get("summary", "")[:150]
            articles.append(f"[{ts.strftime('%Y-%m-%d %H:%M')}] {source}: {headline}\n  {summary}")

        if not articles:
            return "No recent general market news found via Finnhub."

        return f"Finnhub Market News ({category}):\n\n" + "\n\n".join(articles)
    except Exception as e:
        return f"Finnhub market news unavailable: {e}"


def get_company_sentiment(symbol: str) -> dict:
    """
    Get social/news sentiment score from Finnhub.
    Returns: {symbol, buzz_score, sentiment_score, articles_last_week, articles_mention}
    """
    try:
        client = _get_client()
        sentiment = client.news_sentiment(symbol.upper())

        return {
            "symbol": symbol,
            "source": "finnhub",
            "buzz_score": sentiment.get("buzz", {}).get("buzz", 0),
            "articles_last_week": sentiment.get("buzz", {}).get("articlesInLastWeek", 0),
            "articles_mention": sentiment.get("buzz", {}).get("weeklyAverage", 0),
            "sentiment_score": sentiment.get("companyNewsScore", 0),
            "sector_avg_bullish": sentiment.get("sectorAverageBullishPercent", 0),
            "sector_avg_score": sentiment.get("sectorAverageNewsScore", 0),
        }
    except Exception as e:
        return {"symbol": symbol, "source": "finnhub", "error": str(e)}


def get_earnings_calendar(symbol: str, days_ahead: int = 7) -> dict:
    """
    Get earnings calendar from Finnhub — more reliable than yfinance.
    Returns: {symbol, date, eps_estimate, revenue_estimate, quarter}
    """
    try:
        client = _get_client()
        today = datetime.now(timezone.utc).date()
        end = today + timedelta(days=days_ahead)

        calendar = client.earnings_calendar(
            _from=today.isoformat(),
            to=end.isoformat(),
            symbol=symbol.upper()
        )

        earnings = calendar.get("earningsCalendar", [])
        if not earnings:
            return {"symbol": symbol, "has_earnings": False}

        next_earnings = earnings[0]
        return {
            "symbol": symbol,
            "has_earnings": True,
            "date": next_earnings.get("date"),
            "eps_estimate": next_earnings.get("epsEstimate"),
            "revenue_estimate": next_earnings.get("revenueEstimate"),
            "quarter": next_earnings.get("quarter"),
            "year": next_earnings.get("year"),
            "days_until": (datetime.strptime(next_earnings["date"], "%Y-%m-%d").date() - today).days,
        }
    except Exception as e:
        return {"symbol": symbol, "has_earnings": False, "error": str(e)}


def is_available() -> bool:
    return FINNHUB_AVAILABLE and bool(FINNHUB_KEY)
