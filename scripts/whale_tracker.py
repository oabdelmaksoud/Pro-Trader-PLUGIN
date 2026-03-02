#!/usr/bin/env python3
"""
whale_tracker.py — Track top traders: congressional, insider (Form 4), 13F, unusual options flow
Posts alpha signals to #war-room when actionable trades detected.

Sources:
  - House Stock Watcher (STOCK Act disclosures)
  - Senate Stock Watcher (STOCK Act disclosures)
  - SEC EDGAR Form 4 (insider trades, 2-day lag)
  - OpenInsider RSS (insider buy screener)
  - Finnhub unusual options flow
"""

import sys
import os
import json
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv
load_dotenv(REPO / ".env")

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
QUIVERQUANT_KEY = os.getenv("QUIVERQUANT_API_KEY", "")
DISCORD_WAR_ROOM = "1469763123010342953"
DISCORD_BREAKING = "1477247545322246198"

WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AMD", "TSLA",
    "PLTR", "CRWD", "ARM", "MSTR", "XOM", "CVX", "LMT", "RTX", "NOC",
    "JPM", "GS", "BAC", "LLY", "PFE", "MRNA", "AMGN"
]

CACHE_FILE = REPO / "logs" / "whale_cache.json"


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except:
            pass
    return {"seen": [], "last_run": None}


def save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def is_seen(cache, key):
    return key in cache.get("seen", [])


def mark_seen(cache, key):
    if key not in cache["seen"]:
        cache["seen"].append(key)
    # Keep last 500
    cache["seen"] = cache["seen"][-500:]


def post_discord(channel_id, message):
    """Post to Discord via openclaw CLI."""
    import subprocess
    # Split if too long
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", channel_id, "--message", chunk],
            capture_output=True, timeout=15
        )


def check_congressional_trades(cache):
    """Check congressional STOCK Act disclosures.
    Primary: QuiverQuant free API
    Fallback: Capitol Trades RSS
    (housestockwatcher.com / senatestockwatcher.com removed — DNS unreachable in sandbox)
    """
    import re as _re
    alerts = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=5)
    sources_tried = []

    # Source 1: QuiverQuant (free tier — requires QUIVERQUANT_API_KEY in .env)
    # Get free key at: https://www.quiverquant.com/
    if not QUIVERQUANT_KEY:
        sources_tried.append("QuiverQuant ⏭️ (no key — add QUIVERQUANT_API_KEY to .env)")
    else:
      try:
        r = requests.get(
            "https://api.quiverquant.com/beta/live/congresstrading",
            headers={"User-Agent": "CooperCorp/1.0", "Authorization": f"Token {QUIVERQUANT_KEY}"}, timeout=10
        )
        if r.status_code == 200:
            trades = r.json() if isinstance(r.json(), list) else []
            sources_tried.append("QuiverQuant ✅")
            for tx in trades[:100]:
                ticker = tx.get("Ticker", "").upper().strip()
                if not ticker or ticker == "--":
                    continue
                name = tx.get("Representative", "Unknown")
                tx_type = tx.get("Transaction", "").lower()
                date_str = tx.get("Date", tx.get("ReportDate", ""))
                amount = tx.get("Range", "Unknown")
                chamber = tx.get("Chamber", "Congress")
                key = f"qq:{name}:{ticker}:{date_str}:{tx_type}"
                if is_seen(cache, key):
                    continue
                if ticker not in WATCHLIST and not any(x in str(amount) for x in ["250,001", "500,001", "1,000,001"]):
                    continue
                try:
                    tx_date = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if tx_date < cutoff:
                        continue
                except Exception:
                    pass
                direction = "🟢 BUY" if "purchase" in tx_type or "buy" in tx_type else "🔴 SELL"
                alerts.append({
                    "type": "congressional", "key": key, "ticker": ticker,
                    "direction": "long" if "purchase" in tx_type else "short",
                    "message": (
                        f"🏛️ CONGRESSIONAL TRADE — {chamber.upper()} | {date_str}\n"
                        f"👤 {name}\n📊 {direction} {ticker} | {amount}\n"
                        f"🔗 https://www.quiverquant.com/congresstrading\n— Cooper 🦅 | Whale Tracker"
                    ),
                })
                mark_seen(cache, key)
        else:
            sources_tried.append(f"QuiverQuant ❌ ({r.status_code})")
    except Exception as e:
        sources_tried.append(f"QuiverQuant ❌ ({e})")

    # Source 2: Capitol Trades RSS fallback
    if not alerts:
        try:
            import feedparser as _fp
            feed = _fp.parse("https://www.capitoltrades.com/rss.xml")
            if feed.entries:
                sources_tried.append("CapitolTrades ✅")
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    m = _re.search(r"\b([A-Z]{2,5})\b", title)
                    ticker = m.group(1) if m else ""
                    if not ticker or ticker not in WATCHLIST:
                        continue
                    key = f"ct:{title[:60]}"
                    if is_seen(cache, key):
                        continue
                    direction_str = "BUY" if any(w in title.lower() for w in ["bought","purchase"]) else "SELL"
                    alerts.append({
                        "type": "congressional", "key": key, "ticker": ticker,
                        "direction": direction_str.lower(),
                        "message": (
                            f"🏛️ CONGRESSIONAL TRADE\n📰 {title}\n"
                            f"{'🟢' if direction_str=='BUY' else '🔴'} {direction_str} {ticker}\n"
                            f"🔗 {link}\n— Cooper 🦅 | Whale Tracker"
                        ),
                    })
                    mark_seen(cache, key)
            else:
                sources_tried.append("CapitolTrades ❌ (empty)")
        except Exception as e:
            sources_tried.append(f"CapitolTrades ❌ ({e})")

    print(f"  Congressional sources: {', '.join(sources_tried) or 'all failed'}")
    print(f"  Congressional alerts: {len(alerts)}")
    return alerts

def check_insider_form4(cache):
    """Check SEC EDGAR Form 4 RSS for recent insider buys."""
    alerts = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)

    # OpenInsider RSS — insider buys only (cluster buys, large buys)
    feeds = [
        ("OpenInsider-ClusterBuys", "http://openinsider.com/rss?s=&o=fd&pl=&ph=&ll=&lh=&fd=-2&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=2&xp=1&vl=500&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=40&action=getdata"),
        ("SEC-Form4", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&dateb=&owner=include&count=20&search_text=&output=atom"),
    ]

    for name, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")

                # Check for watchlist tickers in title/summary
                matched_ticker = None
                for ticker in WATCHLIST:
                    if ticker in title.upper() or ticker in summary.upper():
                        matched_ticker = ticker
                        break

                if not matched_ticker:
                    continue

                # Only buys
                is_buy = any(word in title.lower() + summary.lower()
                             for word in ["purchase", "bought", "buy", "acquired"])
                if not is_buy and "form4" not in name.lower():
                    continue

                key = f"insider:{name}:{title[:80]}"
                if is_seen(cache, key):
                    continue

                # Parse date
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    import calendar
                    pub_dt = datetime.fromtimestamp(calendar.timegm(pub), tz=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                alerts.append({
                    "type": "insider",
                    "key": key,
                    "message": (
                        f"📋 INSIDER TRADE — FORM 4 | {matched_ticker}\n"
                        f"📰 {title[:120]}\n"
                        f"⚡ C-suite buy signal: {matched_ticker}\n"
                        f"🔗 {link}\n"
                        f"— Cooper 🦅 | Whale Tracker"
                    ),
                    "ticker": matched_ticker,
                    "direction": "long",
                })
                mark_seen(cache, key)

        except Exception as e:
            print(f"[{name}] Error: {e}")

    return alerts


def check_unusual_options(cache):
    """Check Finnhub for unusual options activity on watchlist."""
    alerts = []
    if not FINNHUB_KEY:
        return alerts

    for ticker in WATCHLIST[:10]:  # Top 10 to stay within rate limits
        try:
            r = requests.get(
                f"https://finnhub.io/api/v1/stock/option-chain?symbol={ticker}&token={FINNHUB_KEY}",
                timeout=5
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not data or "data" not in data:
                continue

            # Look for unusual volume (>5x average open interest)
            for contract in (data.get("data") or [])[:5]:
                for opt in contract.get("options", {}).get("CALL", []) + contract.get("options", {}).get("PUT", []):
                    volume = opt.get("volume", 0) or 0
                    oi = opt.get("openInterest", 1) or 1
                    if volume > 5 * oi and volume > 1000:
                        key = f"options:{ticker}:{opt.get('contractName','')}"
                        if is_seen(cache, key):
                            continue
                        opt_type = "CALL 🟢" if "C" in opt.get("contractName", "") else "PUT 🔴"
                        alerts.append({
                            "type": "options_flow",
                            "key": key,
                            "message": (
                                f"🌊 UNUSUAL OPTIONS FLOW — {ticker}\n"
                                f"📊 {opt_type} | Strike: ${opt.get('strike')} | Exp: {opt.get('expirationDate')}\n"
                                f"📈 Volume: {volume:,} vs OI: {oi:,} ({volume/oi:.0f}x normal)\n"
                                f"⚡ Whale activity detected: {ticker}\n"
                                f"— Cooper 🦅 | Whale Tracker"
                            ),
                            "ticker": ticker,
                            "direction": "long" if "C" in opt.get("contractName", "") else "short",
                        })
                        mark_seen(cache, key)

        except Exception as e:
            print(f"[{ticker} options] Error: {e}")
            import time; time.sleep(0.2)

    return alerts


def main():
    print(f"🐋 Whale Tracker | {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    cache = load_cache()

    all_alerts = []

    print("\n[1/3] Congressional trades...")
    congressional = check_congressional_trades(cache)
    print(f"  Found: {len(congressional)}")
    all_alerts.extend(congressional)

    print("\n[2/3] Insider Form 4...")
    insider = check_insider_form4(cache)
    print(f"  Found: {len(insider)}")
    all_alerts.extend(insider)

    print("\n[3/3] Unusual options flow...")
    options = check_unusual_options(cache)
    print(f"  Found: {len(options)}")
    all_alerts.extend(options)

    print(f"\n📊 Total alerts: {len(all_alerts)}")

    for alert in all_alerts:
        print(f"\n🚨 {alert['type'].upper()}: {alert['ticker']}")
        print(alert['message'])
        post_discord(DISCORD_WAR_ROOM, alert['message'])

    if not all_alerts:
        print("✅ No new whale activity detected.")

    cache["last_run"] = datetime.now(timezone.utc).isoformat()
    save_cache(cache)
    print("\nDone.")


if __name__ == "__main__":
    main()
