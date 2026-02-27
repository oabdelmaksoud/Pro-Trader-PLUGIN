"""
CooperCorp PRJ-002 — Reddit Sentiment Integration
Uses PRAW to scan r/wallstreetbets, r/stocks, r/investing for ticker mentions.
Free — requires Reddit app credentials (create at reddit.com/prefs/apps)
"""
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter

try:
    import praw
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "CooperCorpTrading/1.0")


def _get_reddit():
    if not PRAW_AVAILABLE:
        raise ImportError("praw not installed. Run: pip install praw")
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        raise ValueError("REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET not set")
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
        check_for_async=False,
    )


def get_wsb_mentions(symbol: str, hours_back: int = 24, limit: int = 100) -> dict:
    """
    Scan r/wallstreetbets for ticker mentions in last N hours.
    Returns: {symbol, mention_count, sentiment, top_posts, hot_score}
    """
    try:
        reddit = _get_reddit()
        subreddit = reddit.subreddit("wallstreetbets+stocks+investing+stockmarket")

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        symbol_upper = symbol.upper()

        mentions = []
        bullish_signals = ["moon", "🚀", "calls", "buy", "bull", "long", "bullish", "buy the dip", "🐂", "pump"]
        bearish_signals = ["puts", "short", "crash", "dump", "bear", "bearish", "sell", "⬇️", "🐻"]

        for post in subreddit.search(symbol_upper, sort="new", time_filter="day", limit=limit):
            created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
            if created < cutoff:
                continue

            text = f"{post.title} {post.selftext}".lower()
            if symbol_upper.lower() not in text and f"${symbol_upper.lower()}" not in text:
                continue

            bull_count = sum(1 for s in bullish_signals if s in text)
            bear_count = sum(1 for s in bearish_signals if s in text)

            mentions.append({
                "title": post.title[:100],
                "score": post.score,
                "comments": post.num_comments,
                "url": post.url,
                "sentiment": "bullish" if bull_count > bear_count else "bearish" if bear_count > bull_count else "neutral",
                "created": created.isoformat(),
            })

        if not mentions:
            return {"symbol": symbol, "source": "reddit", "mention_count": 0, "sentiment": "neutral", "top_posts": []}

        bull = sum(1 for m in mentions if m["sentiment"] == "bullish")
        bear = sum(1 for m in mentions if m["sentiment"] == "bearish")
        overall = "bullish" if bull > bear else "bearish" if bear > bull else "neutral"

        # Hot score: weighted by post score + comments
        hot_score = sum(m["score"] + m["comments"] * 2 for m in mentions)
        top_posts = sorted(mentions, key=lambda x: x["score"] + x["comments"], reverse=True)[:5]

        return {
            "symbol": symbol,
            "source": "reddit",
            "mention_count": len(mentions),
            "bullish_count": bull,
            "bearish_count": bear,
            "sentiment": overall,
            "hot_score": hot_score,
            "top_posts": top_posts,
            "hours_scanned": hours_back,
        }
    except Exception as e:
        return {"symbol": symbol, "source": "reddit", "error": str(e), "mention_count": 0}


def format_for_analyst(symbol: str, hours_back: int = 24) -> str:
    """Returns Reddit sentiment formatted for LLM consumption."""
    data = get_wsb_mentions(symbol, hours_back)

    if "error" in data:
        return f"Reddit sentiment unavailable for {symbol}: {data['error']}"

    if data["mention_count"] == 0:
        return f"No Reddit mentions found for {symbol} in the last {hours_back} hours."

    posts_text = "\n".join([
        f"  [{p['sentiment'].upper()}] Score:{p['score']} Comments:{p['comments']} — {p['title']}"
        for p in data["top_posts"]
    ])

    return f"""Reddit Sentiment for ${symbol} (last {hours_back}h):
Mentions: {data['mention_count']} | Bullish: {data['bullish_count']} | Bearish: {data['bearish_count']}
Overall: {data['sentiment'].upper()} | Hot Score: {data['hot_score']}

Top Posts:
{posts_text}"""


def is_available() -> bool:
    return PRAW_AVAILABLE and bool(REDDIT_CLIENT_ID) and bool(REDDIT_CLIENT_SECRET)
