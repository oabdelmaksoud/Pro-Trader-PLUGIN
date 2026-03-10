"""Breaking News Monitor Plugin — wraps scan_run.py / breaking_news_monitor.py."""

from __future__ import annotations
import hashlib
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pro_trader.core.interfaces import MonitorPlugin

logger = logging.getLogger(__name__)


class NewsMonitorPlugin(MonitorPlugin):
    name = "news"
    version = "1.0.0"
    description = "Breaking news monitor via RSS feeds and Finnhub"
    interval = 120  # 2 minutes

    def __init__(self):
        self._dedup_path = Path("logs/news_dedup.json")
        self._dedup: dict = {}
        self._feeds = [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://www.marketwatch.com/rss/topstories",
        ]
        self._tickers = ["NVDA", "AAPL", "SPY", "QQQ", "TSLA"]

    def configure(self, config: dict) -> None:
        if config.get("feeds"):
            self._feeds = config["feeds"]
        if config.get("tickers"):
            self._tickers = config["tickers"]

    def startup(self) -> None:
        if self._dedup_path.exists():
            try:
                self._dedup = json.loads(self._dedup_path.read_text())
            except Exception:
                self._dedup = {}

    def check(self) -> list[dict]:
        alerts = []
        try:
            import feedparser
        except ImportError:
            logger.debug("feedparser not installed — news monitor disabled")
            return alerts

        window = datetime.now(timezone.utc) - timedelta(minutes=5)

        for feed_url in self._feeds:
            try:
                feed = feedparser.parse(feed_url)
                source = feed.feed.get("title", feed_url[:40])
                for entry in feed.entries[:5]:
                    title = entry.get("title", "").strip()
                    if not title:
                        continue
                    key = hashlib.md5(title[:80].encode()).hexdigest()
                    if key in self._dedup:
                        continue
                    self._dedup[key] = time.time()
                    alerts.append({
                        "type": "breaking_news",
                        "severity": "info",
                        "message": title,
                        "data": {
                            "source": source,
                            "url": entry.get("link", ""),
                            "title": title,
                        },
                    })
            except Exception as e:
                logger.debug(f"Feed error {feed_url[:40]}: {e}")

        # Persist dedup
        try:
            self._dedup_path.parent.mkdir(parents=True, exist_ok=True)
            self._dedup_path.write_text(json.dumps(self._dedup))
        except Exception:
            pass

        return alerts

    def get_state(self) -> dict:
        return {"dedup_entries": len(self._dedup), "feeds": len(self._feeds)}
