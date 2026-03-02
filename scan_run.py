#!/usr/bin/env python3
"""PRJ-002 Breaking News Monitor — single scan run"""
import json, time, hashlib, os, requests, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import feedparser

# Step 1 — Load dedup cache
dedup_path = Path('/Users/omarabdelmaksoud/.openclaw/workspace/prj-002/protrader/logs/news_dedup.json')
dedup = json.loads(dedup_path.read_text()) if dedup_path.exists() else {}
now = time.time()
print(f'[DEDUP] {len(dedup)} entries loaded', flush=True)

# Step 2 — RSS (parallel, 30s total timeout)
RSS_FEEDS = [
    'https://feeds.reuters.com/reuters/businessNews',
    'https://feeds.reuters.com/reuters/topNews',
    'https://www.cnbc.com/id/100003114/device/rss/rss.html',
    'https://feeds.bloomberg.com/markets/news.rss',
    'https://www.marketwatch.com/rss/topstories',
    'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
    'https://www.wsj.com/xml/rss/3_7031.xml',
    'https://www.ft.com/?format=rss',
    'https://www.economist.com/finance-and-economics/rss.xml',
    'https://feeds.washingtonpost.com/rss/business',
    'https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/business/rss.xml',
    'https://feeds.foxbusiness.com/foxbusiness/latest',
    'https://www.nasdaq.com/feed/rssoutbound?category=Markets',
    'https://seekingalpha.com/feed.xml',
    'https://feeds.content.dowjones.io/public/rss/mw_bulletins',
    'https://www.aljazeera.com/xml/rss/all.xml',
    'https://feeds.reuters.com/reuters/worldNews',
    'https://moxie.foxnews.com/google-publisher/latest.xml',
    'https://www.sec.gov/rss/litigation/litreleases.xml',
    'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml',
]

window_start = datetime.now(timezone.utc) - timedelta(minutes=4)

def fetch_feed(feed_url):
    results = []
    try:
        feed = feedparser.parse(feed_url)
        source_title = feed.feed.get('title', feed_url[:40])
        for entry in feed.entries[:5]:
            published = entry.get('published_parsed') or entry.get('updated_parsed')
            if published:
                try:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < window_start:
                        continue
                except Exception:
                    pass
            title = entry.get('title', '').strip()
            link = entry.get('link', '')
            if not title:
                continue
            key = hashlib.md5(title[:80].encode()).hexdigest()
            if key in dedup:
                continue
            results.append({'title': title, 'url': link, 'key': key, 'source': source_title})
    except Exception as e:
        pass
    return results

rss_stories = []
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(fetch_feed, url): url for url in RSS_FEEDS}
    try:
        for future in as_completed(futures, timeout=25):
            try:
                rss_stories.extend(future.result())
            except Exception:
                pass
    except Exception:
        pass

print(f'[RSS] {len(rss_stories)} fresh stories', flush=True)
for s in rss_stories:
    print(f'  RSS [{s["source"][:30]}]: {s["title"][:90]}', flush=True)

# Step 3 — Finnhub
env_path = Path('/Users/omarabdelmaksoud/.openclaw/workspace/prj-002/protrader/.env')
FINNHUB_KEY = ''
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith('FINNHUB_API_KEY='):
            FINNHUB_KEY = line.split('=', 1)[1].strip().strip('"\'')

TICKERS = ['NVDA', 'MSFT', 'AAPL', 'GOOGL', 'META', 'AMZN', 'AMD', 'TSLA', 'SPY', 'QQQ']
finnhub_stories = []
cutoff_ts = int(window_start.timestamp())

if FINNHUB_KEY:
    for ticker in TICKERS:
        try:
            r = requests.get(
                f'https://finnhub.io/api/v1/company-news?symbol={ticker}&from=2020-01-01&to=2099-01-01&token={FINNHUB_KEY}',
                timeout=4
            )
            if r.status_code == 200:
                for article in (r.json() or [])[:3]:
                    if article.get('datetime', 0) < cutoff_ts:
                        continue
                    title = article.get('headline', '').strip()
                    url = article.get('url', '')
                    if not title:
                        continue
                    key = hashlib.md5(f'{ticker}:{title[:60]}'.encode()).hexdigest()
                    if key in dedup:
                        continue
                    finnhub_stories.append({'title': title, 'url': url, 'key': key, 'ticker': ticker})
                    print(f'  FH [{ticker}]: {title[:80]}', flush=True)
        except Exception as e:
            pass
else:
    print('[FH] No API key', flush=True)

print(f'[FH] {len(finnhub_stories)} fresh stories', flush=True)

all_stories = rss_stories + finnhub_stories
print(f'[TOTAL] {len(all_stories)} fresh stories to classify', flush=True)

# Write intermediate results
out = {
    'rss': rss_stories,
    'finnhub': finnhub_stories,
    'dedup': dedup,
    'now': now,
    'window_start': window_start.isoformat()
}
Path('/tmp/scan_results.json').write_text(json.dumps(out))
print('[DONE] Results written to /tmp/scan_results.json', flush=True)
