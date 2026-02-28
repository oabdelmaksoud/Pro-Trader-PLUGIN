"""
CooperCorp PRJ-002 — News Aggregator
Pulls from 6 free real-time sources, deduplicates, scores relevance.

Sources (all free, no API key except Finnhub/NewsAPI already in .env):
  1. Yahoo Finance RSS  — ticker-specific headlines (real-time)
  2. PR Newswire RSS    — official press releases (real-time)
  3. MarketWatch RSS    — market top stories (real-time)
  4. Finnhub            — company + market news (real-time, 60 req/min)
  5. NewsAPI            — 80,000+ sources (real-time, 100 req/day)
  6. Google News RSS    — broad news (real-time)

Usage:
    from tradingagents.dataflows.news_aggregator import get_news, get_ticker_news

    # All market news (last 2h)
    items = get_news(limit=20)

    # Ticker-specific news
    items = get_ticker_news('NVDA', limit=10)

    # Each item: {title, summary, url, source, published_ts, sentiment, tickers, relevance}
"""
import os, re, time, hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from pathlib import Path

_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

import requests

# ── Config ────────────────────────────────────────────────────────────────────
FINNHUB_KEY  = os.getenv("FINNHUB_API_KEY", "")
NEWSAPI_KEY  = os.getenv("NEWS_API_KEY", "")
MAX_AGE_HOURS = 4   # ignore articles older than this

# Simple sentiment keywords
POS_WORDS = {"beat", "surge", "rally", "upgrade", "record", "soar", "bullish",
             "buyout", "deal", "partnership", "growth", "profit", "dividend"}
NEG_WORDS = {"miss", "drop", "fall", "downgrade", "recall", "fraud", "loss",
             "bearish", "cut", "layoff", "halt", "investigation", "decline", "warning"}


# ── Dedup cache ───────────────────────────────────────────────────────────────
_seen_hashes: set = set()

def _hash(title: str) -> str:
    return hashlib.md5(title.lower().strip()[:80].encode()).hexdigest()

def _is_dup(title: str) -> bool:
    h = _hash(title)
    if h in _seen_hashes:
        return True
    _seen_hashes.add(h)
    return False


# ── Sentiment ─────────────────────────────────────────────────────────────────
def _sentiment(text: str) -> str:
    t = text.lower()
    pos = sum(1 for w in POS_WORDS if w in t)
    neg = sum(1 for w in NEG_WORDS if w in t)
    if pos > neg:    return "bullish"
    if neg > pos:    return "bearish"
    return "neutral"


# ── Ticker extraction ─────────────────────────────────────────────────────────
_TICKER_RE = re.compile(r'\b([A-Z]{1,5})\b')
_COMMON_WORDS = {"A", "I", "US", "UK", "EU", "CEO", "CFO", "AI", "EPS", "IPO",
                 "SEC", "FDA", "ETF", "GDP", "CPI", "PPI", "IT", "HR", "Q1",
                 "Q2", "Q3", "Q4", "YOY", "QOQ", "MOM", "PE", "PB", "EV"}

def _extract_tickers(text: str) -> List[str]:
    matches = _TICKER_RE.findall(text)
    return [m for m in matches if m not in _COMMON_WORDS and len(m) >= 2]


# ── Relevance scoring ─────────────────────────────────────────────────────────
MARKET_KEYWORDS = {"earnings", "revenue", "guidance", "upgrade", "downgrade",
                   "buyback", "merger", "acquisition", "ipo", "fed", "rate",
                   "inflation", "tariff", "recession", "gdp", "cpi", "ppi"}

def _relevance(title: str, summary: str, watchlist: List[str] = None) -> float:
    text = (title + " " + summary).lower()
    score = 0.0
    # Watchlist ticker mention
    if watchlist:
        for t in watchlist:
            if t.lower() in text:
                score += 3.0
    # Market keywords
    for kw in MARKET_KEYWORDS:
        if kw in text:
            score += 0.5
    return min(10.0, score)


# ── Normalizer ────────────────────────────────────────────────────────────────
def _make_item(title, summary, url, source, published_ts, watchlist=None) -> dict:
    if not title or _is_dup(title):
        return None
    # Age filter
    if published_ts:
        age_h = (time.time() - published_ts) / 3600
        if age_h > MAX_AGE_HOURS:
            return None
    return {
        "title":        title.strip(),
        "summary":      (summary or "")[:200].strip(),
        "url":          url or "",
        "source":       source,
        "published_ts": published_ts,
        "published_fmt": datetime.fromtimestamp(published_ts, tz=timezone.utc).strftime("%H:%M UTC") if published_ts else "",
        "sentiment":    _sentiment(title + " " + (summary or "")),
        "tickers":      _extract_tickers(title),
        "relevance":    _relevance(title, summary or "", watchlist),
    }


# ── Source 1: Yahoo Finance RSS (ticker-specific or top stories) ──────────────
def _yahoo_rss(tickers: List[str] = None, limit: int = 20) -> List[dict]:
    if not HAS_FEEDPARSER:
        return []
    try:
        if tickers:
            sym_str = ",".join(tickers[:10])
            url = f"https://finance.yahoo.com/rss/2.0/headline?s={sym_str}&region=US&lang=en-US"
        else:
            url = "https://finance.yahoo.com/news/rssindex"
        f = feedparser.parse(url)
        items = []
        for e in f.entries[:limit]:
            try:
                ts = time.mktime(e.published_parsed) if hasattr(e, "published_parsed") and e.published_parsed else None
            except Exception:
                ts = None
            item = _make_item(
                title=e.get("title", ""),
                summary=e.get("summary", ""),
                url=e.get("link", ""),
                source="Yahoo Finance",
                published_ts=ts,
                watchlist=tickers,
            )
            if item: items.append(item)
        return items
    except Exception:
        return []


# ── Source 2: PR Newswire RSS ─────────────────────────────────────────────────
def _prnewswire_rss(limit: int = 10) -> List[dict]:
    if not HAS_FEEDPARSER:
        return []
    try:
        f = feedparser.parse("https://www.prnewswire.com/rss/news-releases-list.rss")
        items = []
        for e in f.entries[:limit]:
            try:
                ts = time.mktime(e.published_parsed) if hasattr(e, "published_parsed") and e.published_parsed else None
            except Exception:
                ts = None
            item = _make_item(
                title=e.get("title", ""),
                summary=e.get("summary", "")[:200],
                url=e.get("link", ""),
                source="PR Newswire",
                published_ts=ts,
            )
            if item: items.append(item)
        return items
    except Exception:
        return []


# ── Source 3: MarketWatch RSS ─────────────────────────────────────────────────
def _marketwatch_rss(limit: int = 10) -> List[dict]:
    if not HAS_FEEDPARSER:
        return []
    try:
        f = feedparser.parse("https://feeds.content.dowjones.io/public/rss/mw_topstories")
        items = []
        for e in f.entries[:limit]:
            try:
                ts = time.mktime(e.published_parsed) if hasattr(e, "published_parsed") and e.published_parsed else None
            except Exception:
                ts = None
            item = _make_item(
                title=e.get("title", ""),
                summary=e.get("summary", "")[:200],
                url=e.get("link", ""),
                source="MarketWatch",
                published_ts=ts,
            )
            if item: items.append(item)
        return items
    except Exception:
        return []


# ── Source 4: Finnhub news ────────────────────────────────────────────────────
def _finnhub_news(ticker: str = None, limit: int = 10) -> List[dict]:
    if not FINNHUB_KEY:
        return []
    try:
        if ticker:
            url = "https://finnhub.io/api/v1/company-news"
            today = datetime.now().strftime("%Y-%m-%d")
            week_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            params = {"symbol": ticker, "from": week_ago, "to": today, "token": FINNHUB_KEY}
        else:
            url = "https://finnhub.io/api/v1/news"
            params = {"category": "general", "token": FINNHUB_KEY}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code != 200:
            return []
        data = r.json()
        items = []
        for a in (data if isinstance(data, list) else [])[:limit]:
            item = _make_item(
                title=a.get("headline", ""),
                summary=a.get("summary", "")[:200],
                url=a.get("url", ""),
                source=f"Finnhub/{a.get('source','')}",
                published_ts=float(a.get("datetime", 0)) or None,
                watchlist=[ticker] if ticker else None,
            )
            if item: items.append(item)
        return items
    except Exception:
        return []


# ── Source 5: NewsAPI ─────────────────────────────────────────────────────────
def _newsapi(query: str = "stock market earnings", limit: int = 10) -> List[dict]:
    if not NEWSAPI_KEY:
        return []
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query, "sortBy": "publishedAt", "pageSize": limit,
                "language": "en", "apiKey": NEWSAPI_KEY,
            },
            timeout=5,
        )
        if r.status_code != 200:
            return []
        items = []
        for a in r.json().get("articles", []):
            try:
                ts = datetime.fromisoformat(a["publishedAt"].replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = None
            item = _make_item(
                title=a.get("title", ""),
                summary=a.get("description", "")[:200],
                url=a.get("url", ""),
                source=f"NewsAPI/{a.get('source',{}).get('name','')}",
                published_ts=ts,
            )
            if item: items.append(item)
        return items
    except Exception:
        return []


# ── Source 6: Google News RSS ─────────────────────────────────────────────────
def _google_news(query: str = "stock market", limit: int = 10) -> List[dict]:
    if not HAS_FEEDPARSER:
        return []
    try:
        q = query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={q}+when:1d&hl=en-US&gl=US&ceid=US:en"
        f = feedparser.parse(url)
        items = []
        for e in f.entries[:limit]:
            try:
                ts = time.mktime(e.published_parsed) if hasattr(e, "published_parsed") and e.published_parsed else None
            except Exception:
                ts = None
            item = _make_item(
                title=e.get("title", ""),
                summary="",
                url=e.get("link", ""),
                source="Google News",
                published_ts=ts,
            )
            if item: items.append(item)
        return items
    except Exception:
        return []


# ── Main public API ───────────────────────────────────────────────────────────

def get_ticker_news(ticker: str, limit: int = 15) -> List[dict]:
    """
    Get news specifically about a ticker from all sources.
    Returns list sorted by recency, deduplicated.
    """
    global _seen_hashes
    _seen_hashes = set()  # reset dedup for fresh fetch

    all_items = []
    all_items += _yahoo_rss(tickers=[ticker], limit=limit)
    all_items += _finnhub_news(ticker=ticker, limit=limit)
    all_items += _google_news(query=f"{ticker} stock", limit=10)
    all_items += _newsapi(query=ticker, limit=5)

    # Sort by recency
    all_items.sort(key=lambda x: x.get("published_ts") or 0, reverse=True)
    return all_items[:limit]


def get_news(
    tickers: List[str] = None,
    limit: int = 30,
    min_relevance: float = 0.0,
) -> List[dict]:
    """
    Get broad market news from all sources.
    Optionally filter/boost by watchlist tickers.
    Returns deduplicated, sorted by relevance then recency.
    """
    global _seen_hashes
    _seen_hashes = set()

    all_items = []
    all_items += _yahoo_rss(tickers=tickers, limit=20)
    all_items += _marketwatch_rss(limit=10)
    all_items += _prnewswire_rss(limit=10)
    all_items += _finnhub_news(limit=15)
    all_items += _google_news(query="stock market earnings fed", limit=10)
    all_items += _newsapi(query="earnings upgrade downgrade stock", limit=10)

    # Filter by relevance
    if min_relevance > 0:
        all_items = [i for i in all_items if i["relevance"] >= min_relevance]

    # Sort: relevance first, then recency
    all_items.sort(key=lambda x: (x["relevance"], x.get("published_ts") or 0), reverse=True)
    return all_items[:limit]


def format_news_discord(items: List[dict], title: str = "📰 NEWS FEED", max_items: int = 8) -> str:
    """Format news list for Discord posting."""
    if not items:
        return ""
    sentiment_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
    lines = [f"**{title}**"]
    for item in items[:max_items]:
        se  = sentiment_emoji.get(item["sentiment"], "⚪")
        src = item["source"].split("/")[0][:12]
        ts  = item.get("published_fmt", "")
        lines.append(f"{se} **{item['title'][:80]}**")
        lines.append(f"   └ {src} {ts}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing news aggregator...\n")

    # Test ticker news
    items = get_ticker_news("NVDA", limit=5)
    print(f"NVDA news ({len(items)} items):")
    for i in items[:5]:
        print(f"  [{i['sentiment']:7s}] {i['title'][:70]} [{i['source']}]")

    print()
    # Test broad news
    broad = get_news(tickers=["NVDA", "ARM", "CRWD"], limit=10)
    print(f"Broad market news ({len(broad)} items):")
    for i in broad[:8]:
        print(f"  [{i['sentiment']:7s}] rel={i['relevance']:.1f} | {i['title'][:65]} [{i['source']}]")
