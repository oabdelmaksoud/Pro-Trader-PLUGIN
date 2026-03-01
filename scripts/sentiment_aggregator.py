"""
sentiment_aggregator.py — Multi-source sentiment aggregator
Runs daily at 8 AM ET.
Sources: NewsAPI, Finnhub news sentiment, Reddit WSB (optional).
Outputs -1.0 (very bearish) to +1.0 (very bullish) per ticker.

Integration: get_market_data.py scoring:
  if sentiment_score > 0.5 → +0.3 bonus
  if sentiment_score < -0.5 → -0.3 penalty
"""

import sys
import json
import subprocess
import os
from pathlib import Path
from datetime import datetime, timedelta, date

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass

DISCORD_CHANNEL = "1469763123010342953"
LOGS_DIR = REPO / "logs"
LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = LOGS_DIR / "sentiment_scores.json"

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AMD", "TSLA",
    "PLTR", "CRWD", "ARM", "MSTR", "XOM", "CVX", "LMT", "RTX", "JPM", "LLY", "PFE"
]

POSITIVE_WORDS = {
    "surge", "soar", "rally", "beat", "record", "growth", "profit", "gain",
    "bullish", "strong", "upgrade", "buy", "outperform", "positive", "rise", "up"
}
NEGATIVE_WORDS = {
    "drop", "fall", "miss", "loss", "decline", "cut", "bearish", "weak",
    "downgrade", "sell", "underperform", "negative", "crash", "down", "slump"
}


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[sentiment_aggregator] Discord post failed: {e}")


def newsapi_sentiment(ticker: str) -> float | None:
    if not requests or not NEWSAPI_KEY:
        return None
    try:
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            f"https://newsapi.org/v2/everything"
            f"?q={ticker}&from={yesterday}&language=en&pageSize=20"
            f"&apiKey={NEWSAPI_KEY}"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        if not articles:
            return None

        pos = 0
        neg = 0
        for art in articles:
            text = ((art.get("title") or "") + " " + (art.get("description") or "")).lower()
            words = set(text.split())
            pos += len(words & POSITIVE_WORDS)
            neg += len(words & NEGATIVE_WORDS)

        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total
    except Exception as e:
        print(f"[sentiment_aggregator] NewsAPI error for {ticker}: {e}")
        return None


def finnhub_sentiment(ticker: str) -> float | None:
    if not requests or not FINNHUB_KEY:
        return None
    try:
        url = f"https://finnhub.io/api/v1/news-sentiment?symbol={ticker}&token={FINNHUB_KEY}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        score = data.get("companyNewsScore")
        bullish_pct = data.get("sectorAverageBullishPercent")
        if score is not None:
            # Normalize: score is 0-1 range from Finnhub, convert to -1 to +1
            return (score - 0.5) * 2
        elif bullish_pct is not None:
            return (bullish_pct / 100.0 - 0.5) * 2
        return None
    except Exception as e:
        print(f"[sentiment_aggregator] Finnhub sentiment error for {ticker}: {e}")
        return None


def reddit_wsb_sentiment(ticker: str) -> float | None:
    try:
        import praw
        reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
        reddit_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        reddit_ua = os.getenv("REDDIT_USER_AGENT", "CooperCorp/1.0")
        if not reddit_client_id or not reddit_secret:
            return None
        reddit = praw.Reddit(
            client_id=reddit_client_id,
            client_secret=reddit_secret,
            user_agent=reddit_ua
        )
        subreddit = reddit.subreddit("wallstreetbets")
        mentions = 0
        positive = 0
        for post in subreddit.new(limit=100):
            text = ((post.title or "") + " " + (post.selftext or "")).lower()
            if ticker.lower() in text:
                mentions += 1
                words = set(text.split())
                p = len(words & POSITIVE_WORDS)
                n = len(words & NEGATIVE_WORDS)
                if p > n:
                    positive += 1
        if mentions == 0:
            return None
        return (positive / mentions - 0.5) * 2
    except ImportError:
        return None
    except Exception as e:
        print(f"[sentiment_aggregator] Reddit error for {ticker}: {e}")
        return None


def aggregate_score(scores: list) -> float:
    valid = [s for s in scores if s is not None]
    if not valid:
        return 0.0
    return max(-1.0, min(1.0, sum(valid) / len(valid)))


def main():
    results = {}
    now_iso = datetime.utcnow().isoformat()

    for ticker in WATCHLIST:
        try:
            s1 = newsapi_sentiment(ticker)
            s2 = finnhub_sentiment(ticker)
            s3 = reddit_wsb_sentiment(ticker)

            sources = {}
            if s1 is not None:
                sources["newsapi"] = round(s1, 3)
            if s2 is not None:
                sources["finnhub"] = round(s2, 3)
            if s3 is not None:
                sources["reddit_wsb"] = round(s3, 3)

            score = aggregate_score([s1, s2, s3])
            results[ticker] = {
                "score": round(score, 3),
                "sources": sources,
                "updated": now_iso
            }
            print(f"[sentiment_aggregator] {ticker}: {score:.3f} ({sources})")
        except Exception as e:
            print(f"[sentiment_aggregator] Error on {ticker}: {e}")

    # Write results
    try:
        OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    except Exception as e:
        print(f"[sentiment_aggregator] Failed to write log: {e}")

    # Post top 5 bullish + bearish
    sorted_results = sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True)
    top_bullish = sorted_results[:5]
    top_bearish = sorted_results[-5:][::-1]

    lines = [f"🧠 SENTIMENT SCAN — {date.today().strftime('%Y-%m-%d')}", ""]
    lines.append("🟢 Most Bullish:")
    for ticker, data in top_bullish:
        score = data.get("score", 0)
        lines.append(f"  {ticker}: {score:+.2f}")

    lines.append("\n🔴 Most Bearish:")
    for ticker, data in top_bearish:
        score = data.get("score", 0)
        lines.append(f"  {ticker}: {score:+.2f}")

    lines.append("\n— Cooper 🦅 | Sentiment Aggregator")
    msg = "\n".join(lines)
    print(msg)
    post_to_discord(msg)


if __name__ == "__main__":
    main()
