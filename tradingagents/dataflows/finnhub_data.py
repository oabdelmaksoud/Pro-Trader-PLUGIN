"""
CooperCorp PRJ-002 — Finnhub Data Integration
Free tier key: d5sl8mhr01qmiccaic9gd5sl8mhr01qmiccaica0
Available free: company news, market news, profile, basic financials, insider transactions, earnings calendar
NOT on free: news sentiment scoring (paid plan only)
"""
import os
import time
from datetime import datetime, timezone, timedelta, date

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
    """Get company-specific news from Finnhub (Bloomberg, Reuters, Yahoo, etc.)"""
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
        for item in news[:12]:
            source = item.get("source", "Unknown")
            headline = item.get("headline", "")
            summary = item.get("summary", "")[:200]
            ts = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
            articles.append(f"[{ts.strftime('%Y-%m-%d %H:%M')}] {source}: {headline}\n  {summary}")
        return f"Finnhub News for {symbol} (last {days_back}d):\n\n" + "\n\n".join(articles)
    except Exception as e:
        return f"Finnhub news unavailable: {e}"


def get_market_news(category: str = "general", limit: int = 20) -> str:
    """Get general market news from Finnhub."""
    try:
        client = _get_client()
        news = client.general_news(category, min_id=0)
        if not news:
            return "No general market news found via Finnhub."
        articles = []
        for item in news[:limit]:
            source = item.get("source", "Unknown")
            headline = item.get("headline", "")
            summary = item.get("summary", "")[:150]
            articles.append(f"[{source}] {headline}\n  {summary}")
        return f"Finnhub Market News:\n\n" + "\n\n".join(articles)
    except Exception as e:
        return f"Finnhub market news unavailable: {e}"


def get_company_profile(symbol: str) -> str:
    """Get company profile and key metrics."""
    try:
        client = _get_client()
        profile = client.company_profile2(symbol=symbol.upper())
        fin = client.company_basic_financials(symbol.upper(), "all")
        metrics = fin.get("metric", {})
        return f"""Finnhub Company Profile — {symbol.upper()}:
Name: {profile.get('name')} | Industry: {profile.get('finnhubIndustry')}
Market Cap: ${profile.get('marketCapitalization', 0)/1000:.1f}B | Exchange: {profile.get('exchange')}
P/E (normalized): {metrics.get('peNormalizedAnnual', 'N/A')}
EPS (TTM): ${metrics.get('epsNormalizedAnnual', 'N/A')}
Revenue Growth YoY: {metrics.get('revenueGrowthTTMYoy', 'N/A')}%
52-Week High: ${metrics.get('52WeekHigh', 'N/A')} | Low: ${metrics.get('52WeekLow', 'N/A')}
Beta: {metrics.get('beta', 'N/A')} | ROE: {metrics.get('roeTTM', 'N/A')}%"""
    except Exception as e:
        return f"Finnhub profile unavailable: {e}"


def get_insider_transactions(symbol: str, days_back: int = 30) -> str:
    """Get SEC insider transaction filings from Finnhub."""
    try:
        client = _get_client()
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=days_back)).isoformat()
        data = client.stock_insider_transactions(symbol.upper(), start, end)
        txns = data.get("data", [])
        if not txns:
            return f"No insider transactions found for {symbol} in last {days_back} days."
        lines = []
        for t in txns[:10]:
            action = "SOLD" if t.get("change", 0) < 0 else "BOUGHT"
            shares = abs(t.get("change", 0))
            price = t.get("transactionPrice", 0)
            name = t.get("name", "Unknown")
            dt = t.get("transactionDate", "")
            value = shares * price if price else 0
            lines.append(f"[{dt}] {name}: {action} {shares:,} shares @ ${price:.2f} = ${value:,.0f}")
        buys = sum(1 for t in txns if t.get("change", 0) > 0)
        sells = sum(1 for t in txns if t.get("change", 0) < 0)
        sentiment = "🟢 INSIDERS BUYING" if buys > sells else "🔴 INSIDERS SELLING" if sells > buys else "⚪ MIXED"
        return f"Finnhub Insider Transactions — {symbol} (last {days_back}d):\n{sentiment} ({buys} buys, {sells} sells)\n\n" + "\n".join(lines)
    except Exception as e:
        return f"Finnhub insider transactions unavailable: {e}"


def get_earnings_calendar(symbol: str, days_ahead: int = 60) -> dict:
    """Get earnings calendar from Finnhub."""
    try:
        client = _get_client()
        today = date.today()
        end = today + timedelta(days=days_ahead)
        cal = client.earnings_calendar(
            _from=today.isoformat(), to=end.isoformat(), symbol=symbol.upper()
        )
        earnings = cal.get("earningsCalendar", [])
        if not earnings:
            return {"symbol": symbol, "has_earnings": False}
        next_e = earnings[0]
        days_until = (datetime.strptime(next_e["date"], "%Y-%m-%d").date() - today).days
        return {
            "symbol": symbol, "has_earnings": True,
            "date": next_e.get("date"), "days_until": days_until,
            "eps_estimate": next_e.get("epsEstimate"),
            "revenue_estimate": next_e.get("revenueEstimate"),
            "quarter": next_e.get("quarter"), "year": next_e.get("year"),
        }
    except Exception as e:
        return {"symbol": symbol, "has_earnings": False, "error": str(e)}


def get_quote(symbol: str) -> dict:
    """Get real-time quote from Finnhub."""
    try:
        client = _get_client()
        q = client.quote(symbol.upper())
        return {
            "symbol": symbol, "price": q.get("c"),
            "change": q.get("d"), "change_pct": q.get("dp"),
            "high": q.get("h"), "low": q.get("l"),
            "open": q.get("o"), "prev_close": q.get("pc"),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def is_available() -> bool:
    return FINNHUB_AVAILABLE and bool(FINNHUB_KEY)
