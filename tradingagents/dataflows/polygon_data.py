"""
CooperCorp PRJ-002 — Polygon.io data integration.
Real-time quotes, OHLCV bars, news, and market movers.
"""
import os
import requests
from datetime import date, timedelta
from typing import Optional


class PolygonData:
    BASE = "https://api.polygon.io"

    def __init__(self):
        self.key = os.getenv("POLYGON_API_KEY", "")

    def _get(self, path: str, params: dict = None) -> dict:
        if not self.key:
            return {"error": "POLYGON_API_KEY not set"}
        p = params or {}
        p["apiKey"] = self.key
        try:
            r = requests.get(f"{self.BASE}{path}", params=p, timeout=8)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_quote(self, sym: str) -> dict:
        """Real-time snapshot (delayed on free tier)."""
        data = self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{sym}")
        if "error" in data:
            return data
        ticker = data.get("ticker", {})
        day = ticker.get("day", {})
        prev = ticker.get("prevDay", {})
        return {
            "symbol": sym,
            "price": ticker.get("lastTrade", {}).get("p"),
            "open": day.get("o"),
            "high": day.get("h"),
            "low": day.get("l"),
            "close": day.get("c"),
            "volume": day.get("v"),
            "prev_close": prev.get("c"),
            "change_pct": ticker.get("todaysChangePerc"),
            "vwap": day.get("vw"),
        }

    def get_bars(self, sym: str, days: int = 5, timespan: str = "day") -> list:
        """OHLCV bars."""
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=days + 5)).isoformat()
        data = self._get(
            f"/v2/aggs/ticker/{sym}/range/1/{timespan}/{start}/{end}",
            {"adjusted": "true", "sort": "asc", "limit": days + 5}
        )
        results = data.get("results", [])
        return [
            {"t": r.get("t"), "o": r.get("o"), "h": r.get("h"),
             "l": r.get("l"), "c": r.get("c"), "v": r.get("v"), "vw": r.get("vw")}
            for r in results[-days:]
        ]

    def get_news(self, sym: str, limit: int = 5) -> list:
        """Polygon news feed for a ticker."""
        data = self._get("/v2/reference/news", {"ticker": sym, "limit": limit, "order": "desc"})
        items = data.get("results", [])
        return [
            {
                "title": item.get("title", ""),
                "publisher": item.get("publisher", {}).get("name", ""),
                "published": item.get("published_utc", ""),
                "url": item.get("article_url", ""),
                "sentiment": item.get("insights", [{}])[0].get("sentiment", "") if item.get("insights") else "",
            }
            for item in items
        ]

    def get_movers(self, direction: str = "gainers", limit: int = 10) -> list:
        """Top market movers (gainers or losers)."""
        data = self._get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")
        tickers = data.get("tickers", [])[:limit]
        return [
            {
                "symbol": t.get("ticker"),
                "change_pct": t.get("todaysChangePerc"),
                "price": t.get("day", {}).get("c"),
                "volume": t.get("day", {}).get("v"),
            }
            for t in tickers
        ]

    def is_available(self) -> bool:
        return bool(self.key)
