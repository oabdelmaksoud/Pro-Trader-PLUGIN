"""
CooperCorp PRJ-002 — NewsAPI integration.
Aggregated news from 80,000+ sources.
"""
import os
import requests
from datetime import date, timedelta


class NewsAPIData:
    BASE = "https://newsapi.org/v2"

    def __init__(self):
        self.key = os.getenv("NEWS_API_KEY", "")

    def _get(self, path: str, params: dict = None) -> dict:
        if not self.key:
            return {"error": "NEWS_API_KEY not set"}
        headers = {"X-Api-Key": self.key}
        try:
            r = requests.get(f"{self.BASE}{path}", params=params or {}, headers=headers, timeout=8)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_ticker_news(self, sym: str, limit: int = 5) -> list:
        """News articles mentioning a ticker."""
        from_date = (date.today() - timedelta(days=2)).isoformat()
        data = self._get("/everything", {
            "q": sym,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": limit,
        })
        articles = data.get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "source": a.get("source", {}).get("name", ""),
                "published": a.get("publishedAt", ""),
                "description": a.get("description", "")[:200] if a.get("description") else "",
                "url": a.get("url", ""),
            }
            for a in articles
        ]

    def get_market_headlines(self, limit: int = 10) -> list:
        """Top financial/business headlines."""
        data = self._get("/top-headlines", {
            "category": "business",
            "country": "us",
            "pageSize": limit,
        })
        articles = data.get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "source": a.get("source", {}).get("name", ""),
                "published": a.get("publishedAt", ""),
            }
            for a in articles
        ]

    def is_available(self) -> bool:
        return bool(self.key)
