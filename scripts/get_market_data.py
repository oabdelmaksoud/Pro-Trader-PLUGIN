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


def _get_realtime_price(sym: str) -> float:
    """Get real-time price via Alpaca IEX → Finnhub → Polygon → Webull → yfinance fallback."""
    try:
        from tradingagents.dataflows.realtime_quotes import get_price
        p = get_price(sym)
        if p and p > 0:
            return p
    except Exception:
        pass
    return None


def get_technicals(sym: str) -> dict:
    try:
        tk = yf.Ticker(sym)
        hist = tk.history(period="3mo", interval="1d")
        if hist.empty:
            return {"error": "no data"}
        close = hist["Close"]
        # Use real-time price if available, else fall back to last daily close
        rt_price = _get_realtime_price(sym)
        price = rt_price if rt_price else float(close.iloc[-1])
        prev = float(close.iloc[-1])  # compare to yesterday's close
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


def get_news_headlines(sym: str, limit: int = 8) -> list:
    """Get news from 6 aggregated sources (Yahoo, Finnhub, PRN, MarketWatch, NewsAPI, Google)."""
    try:
        from tradingagents.dataflows.news_aggregator import get_ticker_news
        items = get_ticker_news(sym, limit=limit)
        return [
            {
                "title":     i.get("title", ""),
                "publisher": i.get("source", ""),
                "sentiment": i.get("sentiment", "neutral"),
                "time":      i.get("published_fmt", ""),
                "url":       i.get("url", ""),
            }
            for i in items
        ]
    except Exception:
        # fallback to yfinance
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
    """VIX + Fear & Greed + sector ETF + BTC + IV rank + relative strength."""
    try:
        from tradingagents.dataflows.fear_greed import get_vix, get_fear_greed
        from tradingagents.dataflows.market_context import get_sector_momentum, get_btc_signal
        vix = get_vix()
        fg = get_fear_greed()
        sector = get_sector_momentum(sym) if sym else {}
        btc = get_btc_signal()
        result = {"vix": vix, "fear_greed": fg, "sector_momentum": sector, "btc_signal": btc}

        if sym:
            try:
                from tradingagents.dataflows.iv_percentile import get_iv_rank
                result["iv_rank"] = get_iv_rank(sym)
            except Exception:
                pass
            try:
                from tradingagents.dataflows.relative_strength import get_relative_strength
                result["relative_strength"] = get_relative_strength(sym)
            except Exception:
                pass

        return result
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


def _get_insider_trades(sym: str) -> list:
    """OpenInsider — recent Form 4 insider buys/sells for this ticker."""
    try:
        import requests
        r = requests.get(
            f"https://openinsider.com/screener?s={sym}&o=&pl=&ph=&ll=&lh=&fd=7&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=7&xp=1&xs=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=10&action=1",
            timeout=5, headers={"User-Agent": "Mozilla/5.0"}
        )
        if not r.ok:
            return []
        # Parse HTML table — extract insider transactions
        from html.parser import HTMLParser
        class TableParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows = []
                self.current_row = []
                self.in_td = False
            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self.current_row = []
                elif tag == "td":
                    self.in_td = True
            def handle_endtag(self, tag):
                if tag == "tr" and len(self.current_row) >= 5:
                    self.rows.append(self.current_row[:])
                elif tag == "td":
                    self.in_td = False
            def handle_data(self, data):
                if self.in_td:
                    self.current_row.append(data.strip())
        p = TableParser()
        p.feed(r.text)
        trades = []
        for row in p.rows[1:6]:  # skip header, take top 5
            if len(row) >= 8:
                trades.append({
                    "date": row[1] if len(row) > 1 else "",
                    "name": row[3] if len(row) > 3 else "",
                    "title": row[4] if len(row) > 4 else "",
                    "type": row[5] if len(row) > 5 else "",
                    "value": row[7] if len(row) > 7 else "",
                })
        return trades
    except Exception as e:
        return [{"error": str(e)}]


def _get_congressional_trades(sym: str) -> list:
    """Quiver Quant — recent congressional stock trades for this ticker."""
    try:
        import requests
        r = requests.get(
            f"https://api.quiverquant.com/beta/historical/congresstrading/{sym}",
            headers={"accept": "application/json"}, timeout=5
        )
        if not r.ok:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            {
                "date": t.get("Date", ""),
                "politician": t.get("Politician", ""),
                "party": t.get("Party", ""),
                "transaction": t.get("Transaction", ""),
                "range": t.get("Range", ""),
            }
            for t in data[:5]
        ]
    except Exception as e:
        return [{"error": str(e)}]


def _get_global_context() -> dict:
    """Global indices, commodities, FX — Nikkei, FTSE, DAX, Oil, Gold, DXY."""
    try:
        import yfinance as yf
        global_syms = {
            "nikkei": "^N225", "ftse": "^FTSE", "dax": "^GDAXI",
            "hang_seng": "^HSI", "shanghai": "000001.SS",
            "oil_wti": "CL=F", "oil_brent": "BZ=F", "gold": "GC=F",
            "silver": "SI=F", "nat_gas": "NG=F",
            "dxy": "DX-Y.NYB", "eurusd": "EURUSD=X", "usdjpy": "JPY=X",
        }
        result = {}
        tickers = yf.Tickers(" ".join(global_syms.values()))
        for label, sym in global_syms.items():
            try:
                info = tickers.tickers[sym].fast_info
                result[label] = {
                    "price": round(float(info.last_price), 4) if info.last_price else None,
                    "change_pct": round((float(info.last_price) - float(info.previous_close)) / float(info.previous_close) * 100, 2) if info.last_price and info.previous_close else None,
                }
            except Exception:
                result[label] = {"price": None, "change_pct": None}
        return result
    except Exception as e:
        return {"error": str(e)}


def _get_gov_rss_events() -> list:
    """Recent events from government RSS feeds — Fed, FDA, Treasury, White House, SEC."""
    try:
        import feedparser
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        feeds = [
            ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
            ("FDA", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"),
            ("Treasury", "https://home.treasury.gov/news/press-releases/rss.xml"),
            ("White House", "https://www.whitehouse.gov/feed/"),
            ("SEC Litigation", "https://www.sec.gov/rss/litigation/litreleases.xml"),
            ("DOJ", "https://www.justice.gov/news/rss"),
            ("FTC", "https://www.ftc.gov/feeds/press-releases/rss.xml"),
        ]
        events = []
        for name, url in feeds:
            try:
                f = feedparser.parse(url)
                for e in f.entries[:3]:
                    events.append({
                        "source": name,
                        "title": e.get("title", ""),
                        "url": e.get("link", ""),
                        "published": e.get("published", ""),
                    })
            except Exception:
                pass
        return events[:15]
    except Exception as e:
        return [{"error": str(e)}]


def _get_spotgamma_levels() -> list:
    """SpotGamma gamma exposure + key price levels."""
    try:
        import requests
        r = requests.get(
            "https://spotgamma.com/wp-json/wp/v2/posts?per_page=3&_fields=title,link,date",
            timeout=5
        )
        if not r.ok:
            return []
        return [{"title": p["title"]["rendered"], "url": p["link"], "date": p["date"]} for p in r.json()]
    except Exception as e:
        return [{"error": str(e)}]


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


def _load_monitor_signals(sym: str) -> dict:
    """Load outputs from standalone monitor scripts (dark pool, whale, ETF flows, FOMC)."""
    LOGS = Path(__file__).parent.parent / "logs"
    signals = {}

    # Dark pool activity
    try:
        dp = LOGS / "dark_pool_cache.json"
        if dp.exists():
            data = json.loads(dp.read_text())
            if sym in data:
                signals["dark_pool"] = data[sym]
    except Exception:
        pass

    # Whale/insider tracker
    try:
        wc = LOGS / "whale_cache.json"
        if wc.exists():
            data = json.loads(wc.read_text())
            if sym in data:
                signals["whale_activity"] = data[sym]
    except Exception:
        pass

    # ETF flows (sector rotation)
    try:
        ef = LOGS / "etf_flows.json"
        if ef.exists():
            signals["etf_flows"] = json.loads(ef.read_text())
    except Exception:
        pass

    # FOMC state
    try:
        fs = LOGS / "fomc_state.json"
        if fs.exists():
            signals["fomc"] = json.loads(fs.read_text())
    except Exception:
        pass

    return signals


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
        # New: institutional + insider intelligence
        data["insider_trades"] = _get_insider_trades(sym)
        data["congressional_trades"] = _get_congressional_trades(sym)
        # New: global macro context (shared, cached at call level)
        data["global_context"] = _get_global_context()
        data["gov_rss_events"] = _get_gov_rss_events()
        data["spotgamma_levels"] = _get_spotgamma_levels()
        # New: ML intelligence sources
        try:
            from tradingagents.dataflows.finbert_sentiment import get_ticker_sentiment_score
            all_headlines = []
            for key in ["news", "finnhub_news", "av_news", "polygon_news", "newsapi_news", "google_news"]:
                all_headlines.extend(data.get(key, []) or [])
            data["finbert_sentiment"] = get_ticker_sentiment_score(all_headlines)
        except Exception:
            data["finbert_sentiment"] = None
        try:
            from tradingagents.dataflows.institutional_tracker import get_ticker_institutional_ownership
            data["institutional_ownership"] = get_ticker_institutional_ownership(sym)
        except Exception:
            data["institutional_ownership"] = {}
        try:
            from tradingagents.dataflows.catalyst_feeds import get_catalyst_data
            data["catalyst_data"] = get_catalyst_data(sym)
        except Exception:
            data["catalyst_data"] = {}
        try:
            from tradingagents.dataflows.gex_analysis import get_gex_levels
            data["gex_levels"] = get_gex_levels(sym)
        except Exception:
            data["gex_levels"] = {}
        # Earnings whisper (consensus vs whisper EPS)
        try:
            from tradingagents.dataflows.earnings_whisper import get_whisper_number
            data["earnings_whisper"] = get_whisper_number(sym)
        except Exception:
            data["earnings_whisper"] = {}
        # Reddit sentiment (WSB, r/stocks, r/investing)
        try:
            from tradingagents.dataflows.reddit_sentiment import get_wsb_mentions, is_available as reddit_available
            if reddit_available():
                data["reddit_sentiment"] = get_wsb_mentions(sym, hours_back=24)
            else:
                data["reddit_sentiment"] = {"note": "Reddit credentials not configured"}
        except Exception:
            data["reddit_sentiment"] = {}
        # Monitor outputs (dark pool, whale, ETF flows, FOMC)
        data["monitor_signals"] = _load_monitor_signals(sym)
    return data


def gather_macro_context() -> dict:
    """Standalone macro snapshot — global indices, commodities, FX, gov events, SpotGamma."""
    return {
        "as_of": datetime.now().isoformat(),
        "global_markets": _get_global_context(),
        "gov_rss_events": _get_gov_rss_events(),
        "spotgamma_levels": _get_spotgamma_levels(),
        "market_context": _get_market_context(),
    }


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

    # Insider trades — cluster buys are bullish signal
    insiders = data.get("insider_trades", [])
    buys = [t for t in insiders if isinstance(t, dict) and "P" in t.get("type", "")]
    if len(buys) >= 2:
        score += 0.6  # cluster insider buying
    elif len(buys) == 1:
        score += 0.3

    # Congressional trades — politicians buying = bullish signal
    congress = data.get("congressional_trades", [])
    cong_buys = [t for t in congress if isinstance(t, dict) and "Purchase" in t.get("transaction", "")]
    if cong_buys:
        score += 0.4

    # Global macro risk — if oil/gold spiking or DXY crashing, reduce score for tech
    global_ctx = data.get("global_context", {})
    oil = global_ctx.get("oil_wti", {})
    oil_chg = oil.get("change_pct")
    if oil_chg and oil_chg > 3:
        # Oil spike = risk-off for tech, boost for energy
        fund = data.get("fundamentals", {})
        sector = fund.get("sector", "")
        if "Energy" in sector:
            score += 0.5
        elif "Technology" in sector or "Communication" in sector:
            score -= 0.5

    # Historical win-rate bonus (from signal DB)
    try:
        from tradingagents.db.signal_db import get_ticker_stats
        stats = get_ticker_stats(sym)
        if stats and stats.get("total_signals", 0) >= 5:
            wr = stats.get("win_rate", 0)
            if wr > 0.65:
                score += 0.3
            elif wr < 0.40:
                score -= 0.3
    except Exception:
        pass

    # FinBERT NLP sentiment bonus
    try:
        fb = data.get("finbert_sentiment", {})
        if fb and fb.get("available"):
            fs = fb.get("finbert_score", 0)
            if fs > 0.6:
                score += 0.8
            elif fs > 0.3:
                score += 0.5
            elif fs < -0.6:
                score -= 0.8
            elif fs < -0.3:
                score -= 0.5
    except Exception:
        pass

    # 13F institutional ownership bonus
    try:
        inst = data.get("institutional_ownership", {})
        net_buyers = inst.get("net_buyers", 0)
        if net_buyers >= 3:
            score += 0.6
        elif net_buyers >= 1:
            score += 0.3
    except Exception:
        pass

    # Catalyst feeds bonus (clinical trials, FDA)
    try:
        cat = data.get("catalyst_data", {})
        min_days = cat.get("min_days_to_catalyst")
        if min_days is not None:
            if min_days <= 14:
                score += 0.7
            elif min_days <= 60:
                score += 0.5
    except Exception:
        pass

    # GEX regime bonus
    try:
        gex = data.get("gex_levels", {})
        if gex:
            if gex.get("regime") == "negative_gamma":
                score += 0.2
            if gex.get("call_wall_distance_pct", 99) < 1.0:
                score -= 0.2
            if gex.get("put_wall_distance_pct", 99) < 1.0:
                score += 0.2
    except Exception:
        pass

    # Earnings whisper — high whisper = bar set too high, risk of miss
    try:
        ew = data.get("earnings_whisper", {})
        if ew.get("bar_higher_than_consensus"):
            score -= 0.4  # market expects beat → risk of disappointment
        elif ew.get("spread_pct") is not None and ew["spread_pct"] < -5:
            score += 0.3  # low expectations → easier to beat
    except Exception:
        pass

    # Reddit sentiment bonus
    try:
        reddit = data.get("reddit_sentiment", {})
        mention_count = reddit.get("mention_count", 0)
        if mention_count >= 10:
            reddit_sent = reddit.get("sentiment", "neutral")
            if reddit_sent == "bullish":
                score += 0.4
            elif reddit_sent == "bearish":
                score -= 0.3
            # High WSB buzz = volatile, slight risk penalty
            if mention_count >= 50:
                score -= 0.2  # meme risk
    except Exception:
        pass

    # Dark pool large block activity
    try:
        monitors = data.get("monitor_signals", {})
        dp = monitors.get("dark_pool", {})
        if dp.get("block_trades_today", 0) >= 3:
            score += 0.3  # institutional accumulation signal
    except Exception:
        pass

    # Whale/insider from whale_tracker
    try:
        monitors = data.get("monitor_signals", {})
        whale = monitors.get("whale_activity", {})
        if whale.get("insider_buys", 0) >= 2:
            score += 0.4
        if whale.get("unusual_options_volume"):
            score += 0.3
    except Exception:
        pass

    # FOMC proximity risk
    try:
        monitors = data.get("monitor_signals", {})
        fomc = monitors.get("fomc", {})
        days_to_fomc = fomc.get("days_until_next")
        if days_to_fomc is not None and days_to_fomc <= 2:
            score -= 0.5  # FOMC within 2 days = high volatility risk
        elif days_to_fomc is not None and days_to_fomc <= 5:
            score -= 0.2
    except Exception:
        pass

    return round(min(max(score, 0.0), 9.0), 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=False, default="", help="Comma-separated tickers")
    parser.add_argument("--movers", action="store_true", help="Get top market movers (Tier 3 candidates)")
    parser.add_argument("--gaps", action="store_true", help="Get pre-market gap candidates")
    parser.add_argument("--context", action="store_true", help="Get market-wide context (VIX, F&G, sector, BTC)")
    parser.add_argument("--macro", action="store_true", help="Get full macro snapshot: global markets + gov RSS + SpotGamma")
    parser.add_argument("--full", action="store_true", help="Include fundamentals, options, sentiment, insider, congressional, global macro")
    parser.add_argument("--score", action="store_true", help="Include pre-scores")
    args = parser.parse_args()

    if args.macro:
        print(json.dumps(gather_macro_context(), indent=2))
        return

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
