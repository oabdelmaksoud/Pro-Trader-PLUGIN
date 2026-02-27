"""
CooperCorp PRJ-002 — Social Data LangChain Tools
Wraps Finnhub, Reddit, and Stocktwits data sources for use by analysts.
"""
from langchain_core.tools import tool
from typing import Annotated


@tool
def get_reddit_sentiment(
    ticker: Annotated[str, "Stock ticker symbol (e.g. NVDA)"],
    hours_back: Annotated[int, "Hours to look back (default 24)"] = 24,
) -> str:
    """Get Reddit sentiment from r/wallstreetbets, r/stocks, r/investing for a ticker."""
    from tradingagents.dataflows.reddit_sentiment import format_for_analyst, is_available
    if not is_available():
        return "Reddit API not configured. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env"
    return format_for_analyst(ticker, hours_back)


@tool
def get_stocktwits_sentiment(
    ticker: Annotated[str, "Stock ticker symbol (e.g. NVDA)"],
) -> str:
    """Get Stocktwits retail trader sentiment for a ticker. No API key required."""
    from tradingagents.dataflows.stocktwits_sentiment import format_for_analyst
    return format_for_analyst(ticker)


@tool
def get_finnhub_sentiment(
    ticker: Annotated[str, "Stock ticker symbol (e.g. NVDA)"],
) -> str:
    """Get Finnhub news sentiment score and buzz metrics for a ticker."""
    from tradingagents.dataflows.finnhub_data import get_company_sentiment, is_available
    if not is_available():
        return "Finnhub not configured. Set FINNHUB_API_KEY in .env (free at finnhub.io)"
    data = get_company_sentiment(ticker)
    if "error" in data:
        return f"Finnhub sentiment error: {data['error']}"
    return f"""Finnhub Sentiment for ${ticker}:
Buzz Score: {data.get('buzz_score', 0):.2f} (weekly avg articles: {data.get('articles_mention', 0):.1f})
Articles last week: {data.get('articles_last_week', 0)}
Company news score: {data.get('sentiment_score', 0):.2f}
Sector avg bullish %: {data.get('sector_avg_bullish', 0):.1%}"""


@tool
def get_finnhub_news(
    ticker: Annotated[str, "Stock ticker symbol"],
    days_back: Annotated[int, "Days to look back (default 7)"] = 7,
) -> str:
    """Get company news from Finnhub (Bloomberg, Reuters sources)."""
    from tradingagents.dataflows.finnhub_data import get_company_news, is_available
    if not is_available():
        return "Finnhub not configured. Set FINNHUB_API_KEY in .env"
    return get_company_news(ticker, days_back)


@tool
def get_finnhub_profile(
    ticker: Annotated[str, "Stock ticker symbol (e.g. NVDA)"],
) -> str:
    """Get company profile and key financial metrics from Finnhub (P/E, EPS, beta, 52w range, revenue growth)."""
    from tradingagents.dataflows.finnhub_data import get_company_profile, is_available
    if not is_available():
        return f"Finnhub not configured. Set FINNHUB_API_KEY in .env"
    return get_company_profile(ticker)


@tool
def get_finnhub_insiders(
    ticker: Annotated[str, "Stock ticker symbol (e.g. NVDA)"],
    days_back: Annotated[int, "Days to look back (default 30)"] = 30,
) -> str:
    """Get SEC insider transactions from Finnhub — who is buying or selling internally."""
    from tradingagents.dataflows.finnhub_data import get_insider_transactions, is_available
    if not is_available():
        return f"Finnhub not configured. Set FINNHUB_API_KEY in .env"
    return get_insider_transactions(ticker, days_back)


@tool
def get_finnhub_quote(
    ticker: Annotated[str, "Stock ticker symbol (e.g. NVDA)"],
) -> str:
    """Get real-time quote from Finnhub (price, change%, day range)."""
    from tradingagents.dataflows.finnhub_data import get_quote, is_available
    if not is_available():
        return f"Finnhub not configured. Set FINNHUB_API_KEY in .env"
    data = get_quote(ticker)
    if "error" in data:
        return f"Quote error: {data['error']}"
    return f"{ticker.upper()} @ ${data['price']:.2f} | Change: {data['change_pct']:+.2f}% | H: ${data['high']:.2f} L: ${data['low']:.2f} | Prev close: ${data['prev_close']:.2f}"


@tool
def get_finnhub_market_news() -> str:
    """Get current general market news from Finnhub (Bloomberg, Reuters, CNBC sources)."""
    from tradingagents.dataflows.finnhub_data import get_market_news, is_available
    if not is_available():
        return "Finnhub not configured. Set FINNHUB_API_KEY in .env"
    return get_market_news()
