#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — News Dedup Cache
Persistent file-based dedup for the breaking news monitor.
Prevents re-posting stories already seen within the TTL window.

Usage:
  from scripts.news_dedup import NewsDedup
  dedup = NewsDedup()
  if not dedup.seen('Iran strikes US bases'):
      post_to_discord(...)
      dedup.mark_seen('Iran strikes US bases', tier='TIER1')
"""
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
DEDUP_FILE = REPO_ROOT / "logs" / "news_dedup.json"

# How long to suppress re-posts (seconds)
TTL = {
    "TIER1": 4 * 3600,   # 4 hours — major events shouldn't spam every 3 min
    "TIER2": 2 * 3600,   # 2 hours — notable events
    "DEFAULT": 3600,      # 1 hour fallback
}


class NewsDedup:
    def __init__(self):
        DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self):
        try:
            if DEDUP_FILE.exists():
                with open(DEDUP_FILE) as f:
                    self._cache = json.load(f)
            else:
                self._cache = {}
        except Exception:
            self._cache = {}

    def _save(self):
        try:
            with open(DEDUP_FILE, "w") as f:
                json.dump(self._cache, f, indent=2)
        except Exception:
            pass

    def _key(self, text: str) -> str:
        """Generate a short hash key from the story text."""
        # Normalize: lowercase, strip punctuation, first 200 chars
        normalized = "".join(c.lower() for c in text[:200] if c.isalnum() or c.isspace()).strip()
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    def seen(self, text: str, tier: str = "DEFAULT") -> bool:
        """Return True if this story was recently posted (within TTL)."""
        self._purge_expired()
        key = self._key(text)
        if key not in self._cache:
            return False
        entry = self._cache[key]
        ttl = TTL.get(tier, TTL["DEFAULT"])
        age = time.time() - entry["posted_at"]
        return age < ttl

    def mark_seen(self, text: str, tier: str = "DEFAULT", channels: list = None):
        """Mark a story as posted."""
        key = self._key(text)
        self._cache[key] = {
            "snippet": text[:100],
            "tier": tier,
            "posted_at": time.time(),
            "posted_time": datetime.now(timezone.utc).isoformat(),
            "channels": channels or [],
        }
        self._save()

    def _purge_expired(self):
        """Remove entries older than max TTL."""
        max_ttl = max(TTL.values())
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v["posted_at"] > max_ttl]
        for k in expired:
            del self._cache[k]
        if expired:
            self._save()

    def get_recent(self, hours: int = 4) -> list:
        """List recently posted stories."""
        self._purge_expired()
        cutoff = time.time() - hours * 3600
        recent = [
            v for v in self._cache.values()
            if v["posted_at"] > cutoff
        ]
        return sorted(recent, key=lambda x: x["posted_at"], reverse=True)

    def status(self) -> dict:
        self._purge_expired()
        return {
            "cached_stories": len(self._cache),
            "recent_1h": len([v for v in self._cache.values() if time.time() - v["posted_at"] < 3600]),
            "recent_4h": len([v for v in self._cache.values() if time.time() - v["posted_at"] < 4*3600]),
        }


if __name__ == "__main__":
    dedup = NewsDedup()
    print("Status:", dedup.status())
    print("Recent posts (last 4h):")
    for item in dedup.get_recent(4):
        from datetime import datetime
        age_min = int((time.time() - item["posted_at"]) / 60)
        print(f"  [{item['tier']}] {age_min}m ago: {item['snippet'][:80]}")
