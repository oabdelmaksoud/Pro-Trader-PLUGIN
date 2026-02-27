#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Pure data gathering (no LLM).
Fetches price, technicals, sentiment, news for a list of tickers.
Used by Cooper agent before spawning analyst sub-agents.

Usage:
  python3 scripts/get_market_data.py --tickers NVDA,MSFT,AMD
  python3 scripts/get_market_data.py --tickers NVDA --full
"""
import argparse, json, sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import yfinance as yf
import os


def get_technicals(sym: str) -> dict:
    try:
        tk = yf.Ticker(sym)
        hist = tk.history(period="3mo", interval="1d")
        if hist.empty:
            return {"error": "no data"}
        close = hist["Close"]
        price = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else price
        change_pct = (price - prev) / prev * 100

        # Simple RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = float(100 - (100 / (1 + rs.iloc[-1])))

        # SMA
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        vol = float(hist["Volume"].iloc[-1])
        avg_vol = float(hist["Volume"].rolling(20).mean().iloc[-1])

        return {
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "rsi": round(rsi, 1),
            "above_sma20": price > sma20,
            "above_sma50": price > sma50 if sma50 else None,
            "volume_ratio": round(vol / avg_vol, 2) if avg_vol else None,
            "52w_high": round(float(hist["Close"].max()), 2),
            "52w_low": round(float(hist["Close"].min()), 2),
        }
    except Exception as e:
        return {"error": str(e)}


def get_fundamentals(sym: str) -> dict:
    try:
        tk = yf.Ticker(sym)
        info = tk.info
        return {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margins": info.get("profitMargins"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "short_ratio": info.get("shortRatio"),
        }
    except Exception as e:
        return {"error": str(e)}


def get_news_headlines(sym: str, limit: int = 5) -> list:
    try:
        tk = yf.Ticker(sym)
        news = tk.news or []
        return [
            {"title": n.get("content", {}).get("title", ""), "publisher": n.get("content", {}).get("provider", {}).get("displayName", "")}
            for n in news[:limit]
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_options_flow(sym: str) -> dict:
    try:
        from tradingagents.dataflows.options_flow import OptionsFlowScreener
        screener = OptionsFlowScreener()
        return screener.get_unusual_activity(sym)
    except Exception as e:
        return {"error": str(e)}


def get_sentiment(sym: str) -> dict:
    try:
        from tradingagents.dataflows.stocktwits_sentiment import get_symbol_sentiment
        return get_symbol_sentiment(sym, limit=20)
    except Exception as e:
        return {"error": str(e)}


def get_alpha_vantage_news(sym: str) -> list:
    try:
        key = os.getenv("ALPHA_VANTAGE_KEY", "")
        if not key:
            return [{"note": "ALPHA_VANTAGE_KEY not set"}]
        import requests
        r = requests.get(
            f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={sym}&limit=5&apikey={key}",
            timeout=8
        )
        data = r.json()
        items = data.get("feed", [])[:5]
        return [
            {
                "title": item.get("title", ""),
                "sentiment": item.get("overall_sentiment_label", ""),
                "sentiment_score": item.get("overall_sentiment_score", 0),
                "source": item.get("source", ""),
                "published": item.get("time_published", ""),
            }
            for item in items
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_finnhub_news(sym: str) -> list:
    try:
        from tradingagents.dataflows.finnhub_data import FinnhubData
        fh = FinnhubData()
        return fh.get_company_news(sym, limit=5)
    except Exception as e:
        return [{"error": str(e)}]


def get_polygon_news(sym: str) -> list:
    try:
        from tradingagents.dataflows.polygon_data import PolygonData
        pg = PolygonData()
        if not pg.is_available():
            return [{"note": "POLYGON_API_KEY not set"}]
        return pg.get_news(sym, limit=5)
    except Exception as e:
        return [{"error": str(e)}]


def get_polygon_quote(sym: str) -> dict:
    try:
        from tradingagents.dataflows.polygon_data import PolygonData
        pg = PolygonData()
        if not pg.is_available():
            return {"note": "POLYGON_API_KEY not set"}
        return pg.get_quote(sym)
    except Exception as e:
        return {"error": str(e)}


def get_newsapi_news(sym: str) -> list:
    try:
        from tradingagents.dataflows.newsapi_data import NewsAPIData
        na = NewsAPIData()
        if not na.is_available():
            return [{"note": "NEWS_API_KEY not set"}]
        return na.get_ticker_news(sym, limit=5)
    except Exception as e:
        return [{"error": str(e)}]


def _get_market_context() -> dict:
    """VIX + Fear & Greed — market-wide context for position sizing."""
    try:
        from tradingagents.dataflows.fear_greed import get_vix, get_fear_greed
        vix = get_vix()
        fg = get_fear_greed()
        return {"vix": vix, "fear_greed": fg}
    except Exception as e:
        return {"error": str(e)}


def _get_google_news(sym: str) -> list:
    try:
        from tradingagents.dataflows.google_news import get_ticker_news
        return get_ticker_news(sym, limit=5)
    except Exception as e:
        return [{"error": str(e)}]


def _get_sec_filings(sym: str) -> list:
    try:
        from tradingagents.dataflows.sec_edgar import get_recent_filings
        return get_recent_filings(sym, "8-K", limit=3)
    except Exception as e:
        return [{"error": str(e)}]


def _get_short_interest(sym: str) -> dict:
    try:
        from tradingagents.dataflows.short_interest import get_finviz_short_interest
        return get_finviz_short_interest(sym)
    except Exception as e:
        return {"error": str(e)}


def get_polygon_movers() -> dict:
    """Top gainers and losers — used for Tier 3 dynamic candidates."""
    try:
        from tradingagents.dataflows.polygon_data import PolygonData
        pg = PolygonData()
        if not pg.is_available():
            return {"note": "POLYGON_API_KEY not set"}
        return {
            "gainers": pg.get_movers("gainers", limit=10),
            "losers": pg.get_movers("losers", limit=5),
        }
    except Exception as e:
        return {"error": str(e)}


def gather_ticker_data(sym: str, full: bool = False) -> dict:
    data = {
        "ticker": sym,
        "as_of": datetime.now().isoformat(),
        "technicals": get_technicals(sym),
        "news": get_news_headlines(sym),
        "market_context": _get_market_context() if full else {},
    }
    if full:
        data["fundamentals"] = get_fundamentals(sym)
        data["options_flow"] = get_options_flow(sym)
        data["sentiment"] = get_sentiment(sym)
        data["finnhub_news"] = get_finnhub_news(sym)
        data["av_news"] = get_alpha_vantage_news(sym)
        data["polygon_news"] = get_polygon_news(sym)
        data["newsapi_news"] = get_newsapi_news(sym)
        data["google_news"] = _get_google_news(sym)
        data["sec_filings"] = _get_sec_filings(sym)
        data["short_interest"] = _get_short_interest(sym)
    return data


def score_ticker(data: dict) -> float:
    """Quick pre-score to filter candidates before full LLM analysis."""
    score = 5.0  # baseline
    tech = data.get("technicals", {})
    if tech.get("error"):
        return 0.0

    # Technical signals
    if tech.get("above_sma20"):
        score += 0.3
    if tech.get("above_sma50"):
        score += 0.3
    rsi = tech.get("rsi", 50)
    if 45 < rsi < 70:  # healthy momentum, not overbought
        score += 0.4
    vol_ratio = tech.get("volume_ratio", 1.0)
    if vol_ratio and vol_ratio > 1.5:
        score += 0.5  # elevated volume
    if vol_ratio and vol_ratio > 2.5:
        score += 0.3  # unusual volume

    change = tech.get("change_pct", 0)
    if 1 < change < 5:
        score += 0.3
    elif change > 5:
        score += 0.5  # strong move

    # Options flow bonus
    options = data.get("options_flow", {})
    if options.get("has_unusual_activity") and options.get("sentiment") == "bullish":
        score += 0.7

    # Sentiment
    sent = data.get("sentiment", {})
    bull_pct = sent.get("bull_pct", 0)
    if bull_pct > 60:
        score += 0.4
    elif bull_pct > 40:
        score += 0.2

    return round(min(score, 9.0), 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=False, default="", help="Comma-separated tickers")
    parser.add_argument("--movers", action="store_true", help="Get top market movers (Tier 3 candidates)")
    parser.add_argument("--full", action="store_true", help="Include fundamentals, options, sentiment")
    parser.add_argument("--score", action="store_true", help="Include pre-scores")
    args = parser.parse_args()

    if args.movers:
        print(json.dumps(get_polygon_movers(), indent=2))
        return

    if not args.tickers:
        print(json.dumps({"error": "--tickers required unless --movers"}))
        return

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    results = []

    for sym in tickers:
        data = gather_ticker_data(sym, full=args.full or args.score)
        if args.score:
            data["pre_score"] = score_ticker(data)
        results.append(data)

    # Sort by pre_score if scoring
    if args.score:
        results.sort(key=lambda x: x.get("pre_score", 0), reverse=True)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
