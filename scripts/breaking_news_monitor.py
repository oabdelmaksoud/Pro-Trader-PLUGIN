#!/usr/bin/env python3
"""
PRJ-002: Breaking News Monitor
Standalone script — runs fresh each time (no accumulated session context).
Scans RSS feeds + Finnhub, classifies stories, posts to Discord via openclaw CLI.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ── Config ─────────────────────────────────────────────────────────────────
DEDUP_PATH = REPO / "logs" / "news_dedup.json"
DEDUP_TTL = 14400          # 4 hours
WINDOW_MINUTES = 4         # freshness window
TIMEOUT_RSS = 8            # seconds per feed
TIMEOUT_FINNHUB = 5        # seconds per ticker

BREAKING_NEWS_CHANNEL = "1477247545322246198"
WAR_ROOM_CHANNEL      = "1469763123010342953"

RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/topNews",
    "https://feeds.reuters.com/reuters/worldNews",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://moxie.foxnews.com/google-publisher/latest.xml",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://www.marketwatch.com/rss/topstories",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.wsj.com/xml/rss/3_7031.xml",
    "https://www.ft.com/?format=rss",
    "https://feeds.washingtonpost.com/rss/business",
    "https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/business/rss.xml",
    "https://feeds.foxbusiness.com/foxbusiness/latest",
    "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
    "https://seekingalpha.com/feed.xml",
    "https://www.sec.gov/rss/litigation/litreleases.xml",
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
    "https://feeds.skynews.com/feeds/rss/world.xml",
]

FINNHUB_TICKERS = ["NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AMD", "TSLA", "SPY", "QQQ"]

# ── Tier classification (rule-based, no LLM needed) ─────────────────────────
TIER1_KEYWORDS = [
    "war", "military strike", "attack on", "bombed", "missiles", "invasion",
    "central bank emergency", "fed emergency", "market halt", "circuit breaker",
    "supreme leader", "killed", "dead", "ceasefire", "nuclear",
    "hormuz", "strait closed", "blockade", "default", "exchange halt",
    "assassination", "coup", "overthrow", "martial law",
    "earthquake", "tsunami", "catastrophe",
]
TIER2_KEYWORDS = [
    "earnings surprise", "beats by", "misses by", "acquisition", "merger", "takeover",
    "fda approved", "fda rejected", "fda approval", "fda rejection",
    "congressional", "insider buy", "activist investor", "short squeeze",
    "rate decision", "rate cut", "rate hike", "ceo resign", "ceo fired",
    "ipo prices", "bankruptcy", "chapter 11", "investigation", "fraud",
]
TIER3_KEYWORDS = [
    "upgrade", "downgrade", "price target", "earnings", "revenue", "guidance",
    "product launch", "partnership", "contract", "deal", "quarterly",
    "economic data", "jobs report", "inflation", "gdp", "retail sales",
]
SILENT_KEYWORDS = [
    "premier league", "nfl", "nba", "cricket", "soccer", "football match",
    "world cup", "olympics", "t20", "ipl", "tennis", "golf",
    "opinion:", "analysis:", "explainer:", "how to", "best stocks",
    "top 10", "roundup", "weekly recap",
]


def classify_tier(title: str) -> int:
    """Return 1, 2, 3, or 0 (silent)."""
    t = title.lower()
    for kw in SILENT_KEYWORDS:
        if kw in t:
            return 0
    for kw in TIER1_KEYWORDS:
        if kw in t:
            return 1
    for kw in TIER2_KEYWORDS:
        if kw in t:
            return 2
    for kw in TIER3_KEYWORDS:
        if kw in t:
            return 3
    return 0  # silent by default — only post hard news


def load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        raw = json.loads(DEDUP_PATH.read_text())
        # Filter: must be {str: float} — reject corrupted entries
        now = time.time()
        return {k: v for k, v in raw.items()
                if isinstance(k, str) and isinstance(v, (int, float))
                and now - v < DEDUP_TTL}
    except Exception:
        return {}


def save_dedup(dedup: dict):
    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    clean = {k: v for k, v in dedup.items() if now - v < DEDUP_TTL}
    DEDUP_PATH.write_text(json.dumps(clean))


def story_key(title: str, prefix: str = "") -> str:
    return hashlib.md5(f"{prefix}{title[:80]}".encode()).hexdigest()[:9]


def scan_rss(window_start: datetime, dedup: dict) -> list:
    try:
        import feedparser
    except ImportError:
        print("feedparser not installed — skipping RSS")
        return []

    stories = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < window_start:
                        continue
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                if not title:
                    continue
                key = story_key(title)
                if key in dedup:
                    continue
                tier = classify_tier(title)
                if tier == 0:
                    continue
                stories.append({
                    "title": title, "url": link, "key": key,
                    "tier": tier, "source": feed.feed.get("title", feed_url[:40]),
                })
        except Exception as e:
            print(f"RSS error {feed_url[:40]}: {e}")
    return stories


def scan_finnhub(window_start: datetime, dedup: dict) -> list:
    try:
        import requests
    except ImportError:
        print("requests not installed — skipping Finnhub")
        return []

    # Load .env
    env_path = REPO / ".env"
    api_key = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("FINNHUB_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

    if not api_key:
        print("FINNHUB_API_KEY not found in .env — skipping Finnhub")
        return []

    cutoff_ts = int(window_start.timestamp())
    stories = []
    try:
        import requests as req
    except ImportError:
        return []

    for ticker in FINNHUB_TICKERS:
        try:
            r = req.get(
                f"https://finnhub.io/api/v1/company-news"
                f"?symbol={ticker}&from=2020-01-01&to=2099-01-01&token={api_key}",
                timeout=TIMEOUT_FINNHUB,
            )
            if r.status_code != 200:
                continue
            for article in (r.json() or [])[:5]:
                if article.get("datetime", 0) < cutoff_ts:
                    continue
                title = article.get("headline", "").strip()
                url = article.get("url", "")
                if not title:
                    continue
                key = story_key(title, prefix=ticker)
                if key in dedup:
                    continue
                tier = classify_tier(title)
                if tier == 0:
                    continue
                stories.append({
                    "title": title, "url": url, "key": key,
                    "tier": tier, "source": f"Finnhub/{ticker}",
                })
        except Exception as e:
            print(f"Finnhub error {ticker}: {e}")
    return stories


def post_discord(channel_id: str, message: str):
    """Post to Discord via openclaw CLI."""
    # Split if > 1900 chars
    chunks = []
    while len(message) > 1900:
        split_at = message.rfind("\n", 0, 1900)
        if split_at == -1:
            split_at = 1900
        chunks.append(message[:split_at])
        message = message[split_at:].lstrip()
    chunks.append(message)

    for chunk in chunks:
        try:
            subprocess.run(
                ["openclaw", "message", "send",
                 "--channel", "discord",
                 "--to", channel_id,
                 "--message", chunk],
                timeout=15, check=False, capture_output=True,
            )
        except Exception as e:
            print(f"Discord post error to {channel_id}: {e}")


def format_story(story: dict) -> str:
    tier = story["tier"]
    emoji = {1: "🚨", 2: "⚡", 3: "📰"}.get(tier, "📰")
    label = {1: "TIER 1", 2: "TIER 2", 3: "TIER 3"}.get(tier, "TIER 3")
    lines = [
        f"[{label}: {emoji}] **{story['title']}**",
        f"Source: {story['source']}",
    ]
    if story.get("url"):
        lines.append(f"🔗 {story['url']}")
    return "\n".join(lines)


def main():
    start = time.time()
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(minutes=WINDOW_MINUTES)

    print(f"=== Breaking News Monitor — {now_utc.strftime('%H:%M UTC')} ===")
    print(f"Window: {window_start.strftime('%H:%M')}–{now_utc.strftime('%H:%M')} UTC")

    dedup = load_dedup()
    print(f"Dedup cache: {len(dedup)} entries")

    # Scan sources
    rss_stories = scan_rss(window_start, dedup)
    finnhub_stories = scan_finnhub(window_start, dedup)

    all_stories = rss_stories + finnhub_stories
    print(f"RSS fresh: {len(rss_stories)} | Finnhub fresh: {len(finnhub_stories)}")

    if not all_stories:
        elapsed = time.time() - start
        print(f"\nSILENT PASS — RSS: {len(rss_stories)} | Finnhub: {len(finnhub_stories)} | Posted: 0")
        print(f"Runtime: {elapsed:.0f}s")
        save_dedup(dedup)
        return

    # Post stories
    posted = []
    for story in all_stories:
        tier = story["tier"]
        msg = format_story(story)

        # Post to #breaking-news (all tiers)
        post_discord(BREAKING_NEWS_CHANNEL, msg)

        # Post to #war-room (tier 1 + 2 only)
        if tier <= 2:
            post_discord(WAR_ROOM_CHANNEL, msg)

        dedup[story["key"]] = time.time()
        posted.append(story)
        print(f"POSTED [T{tier}]: {story['title'][:80]}")

    save_dedup(dedup)

    elapsed = time.time() - start
    print(f"\nPOSTED {len(posted)} — RSS: {len(rss_stories)} | Finnhub: {len(finnhub_stories)} | Posted: {len(posted)}")
    print(f"Runtime: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
