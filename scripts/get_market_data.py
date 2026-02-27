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

        # RSI
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

        # MACD (12/26/9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line
        macd_val = float(macd_line.iloc[-1])
        macd_sig = float(signal_line.iloc[-1])
        macd_histogram = float(macd_hist.iloc[-1])
        macd_cross = None
        if len(macd_hist) >= 2:
            prev_hist = float(macd_hist.iloc[-2])
            if prev_hist < 0 and macd_histogram > 0:
                macd_cross = "bullish"  # MACD crossed above signal
            elif prev_hist > 0 and macd_histogram < 0:
                macd_cross = "bearish"  # MACD crossed below signal

        # Bollinger Bands (20, 2)
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = float((bb_mid + 2 * bb_std).iloc[-1])
        bb_lower = float((bb_mid - 2 * bb_std).iloc[-1])
        bb_mid_val = float(bb_mid.iloc[-1])
        bb_position = (price - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5

        return {
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "rsi": round(rsi, 1),
            "above_sma20": price > sma20,
            "above_sma50": price > sma50 if sma50 else None,
            "volume_ratio": round(vol / avg_vol, 2) if avg_vol else None,
            "52w_high": round(float(hist["Close"].max()), 2),
            "52w_low": round(float(hist["Close"].min()), 2),
            "macd": round(macd_val, 4),
            "macd_signal": round(macd_sig, 4),
            "macd_histogram": round(macd_histogram, 4),
            "macd_cross": macd_cross,  # "bullish" | "bearish" | None
            "bb_upper": round(bb_upper, 2),
            "bb_lower": round(bb_lower, 2),
            "bb_position": round(bb_position, 3),  # 0=at lower, 1=at upper, 0.5=mid
            "bb_squeeze": (bb_upper - bb_lower) / bb_mid_val < 0.05,  # tight bands = breakout coming
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


def _get_market_context(sym: str = None) -> dict:
    """VIX + Fear & Greed + sector ETF + BTC signal."""
    try:
        from tradingagents.dataflows.fear_greed import get_vix, get_fear_greed
        from tradingagents.dataflows.market_context import get_sector_momentum, get_btc_signal
        vix = get_vix()
        fg = get_fear_greed()
        sector = get_sector_momentum(sym) if sym else {}
        btc = get_btc_signal()
        return {"vix": vix, "fear_greed": fg, "sector_momentum": sector, "btc_signal": btc}
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
        "market_context": _get_market_context(sym) if full else {},
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

    # MACD signals
    if tech.get("macd_cross") == "bullish":
        score += 0.7  # fresh bullish MACD cross
    elif tech.get("macd_histogram", 0) > 0 and tech.get("macd", 0) > 0:
        score += 0.3  # MACD positive momentum
    if tech.get("bb_squeeze"):
        score += 0.4  # Bollinger squeeze = breakout setup
    bb_pos = tech.get("bb_position", 0.5)
    if 0.4 < bb_pos < 0.7:
        score += 0.2  # healthy mid-band momentum

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
    parser.add_argument("--gaps", action="store_true", help="Get pre-market gap candidates")
    parser.add_argument("--context", action="store_true", help="Get market-wide context (VIX, F&G, sector, BTC)")
    parser.add_argument("--full", action="store_true", help="Include fundamentals, options, sentiment")
    parser.add_argument("--score", action="store_true", help="Include pre-scores")
    args = parser.parse_args()

    if args.movers:
        print(json.dumps(get_polygon_movers(), indent=2))
        return

    if args.gaps:
        from tradingagents.dataflows.market_context import get_premarket_gaps
        print(json.dumps(get_premarket_gaps(), indent=2))
        return

    if args.context:
        print(json.dumps(_get_market_context(), indent=2))
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
