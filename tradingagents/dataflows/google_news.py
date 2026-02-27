"""
CooperCorp PRJ-002 — Google News RSS scraper.
No API key needed. Uses public RSS feeds.
"""
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
from datetime import datetime


def get_ticker_news(sym: str, limit: int = 5) -> list:
    """Fetch Google News RSS articles for a ticker."""
    try:
        query = urllib.parse.quote(f"{sym} stock")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml = resp.read()
        root = ET.fromstring(xml)
        items = root.findall(".//item")[:limit]
        results = []
        for item in items:
            title = item.findtext("title", "")
            pub = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            # Strip HTML from title
            import re
            title = re.sub(r"<[^>]+>", "", title).strip()
            results.append({"title": title, "source": source, "published": pub})
        return results
    except Exception as e:
        return [{"error": str(e)}]


def get_market_news(limit: int = 10) -> list:
    """Fetch Google News RSS for general market news."""
    try:
        url = "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml = resp.read()
        root = ET.fromstring(xml)
        items = root.findall(".//item")[:limit]
        import re
        return [
            {
                "title": re.sub(r"<[^>]+>", "", item.findtext("title", "")).strip(),
                "source": item.findtext("source", ""),
                "published": item.findtext("pubDate", ""),
            }
            for item in items
        ]
    except Exception as e:
        return [{"error": str(e)}]
