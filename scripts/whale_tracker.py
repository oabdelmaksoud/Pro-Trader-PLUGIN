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
    """Congressional STOCK Act disclosure tracker.

    NOTE: All real-time congressional data APIs (QuiverQuant, Unusual Whales,
    Capitol Trades) require paid subscriptions. No free programmatic source exists.

    This function posts a periodic reminder with direct links for manual review.
    Runs every 4 hours — posts reminder only once per trading day (not every cycle).
    """
    from datetime import date as _date
    today = str(_date.today())
    reminder_key = f"congressional_reminder:{today}"

    # Only post the reminder once per day (not every 4h cycle)
    if is_seen(cache, reminder_key):
        print("  Congressional: reminder already sent today")
        return []

    mark_seen(cache, reminder_key)

    # Compose manual check reminder
    msg = (
        "🏛️ **Congressional Trade Monitoring — Manual Check Required**\n"
        "No free real-time API available. Review disclosures directly:\n"
        "• **House STOCK Act**: https://disclosures.house.gov/eFD/\n"
        "• **Senate STOCK Act**: https://efds.senate.gov/\n"
        "• **Capitol Trades** (visual): https://www.capitoltrades.com/\n"
        "• **Unusual Whales** (visual): https://unusualwhales.com/politicians\n"
        "\n_Check for energy (XOM/CVX/COP/SLB) and defense (LMT/RTX/NOC) buys given Iran thesis._\n"
        "— Cooper 🦅 | Whale Tracker"
    )

    print("  Congressional: posting daily manual-check reminder")
    return [{
        "type": "congressional_reminder",
        "key": reminder_key,
        "ticker": None,
        "direction": None,
        "message": msg,
        "channel_override": "1469763123010342953",  # #war-room only
    }]

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


def check_yfinance_insider_buys(cache):
    """Scan watchlist tickers for recent executive/director purchases via yfinance.

    Source: SEC Form 4 filings aggregated by yfinance — completely free.
    Filters for: Purchase transactions only, value > $100k, within last 7 days.
    High-priority: CEO, CFO, President, Director, 10%+ Owner buys.
    """
    alerts = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    HIGH_PRIORITY_TITLES = {"ceo", "cfo", "president", "chairman", "coo", "10%", "owner"}

    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        print("  yfinance not installed — skipping")
        return alerts

    for ticker in WATCHLIST:
        try:
            t = yf.Ticker(ticker)
            ins = t.insider_transactions
            if ins is None or ins.empty:
                continue

            for _, row in ins.iterrows():
                tx_text = str(row.get("Text", "")).lower()
                tx_type = str(row.get("Transaction", "")).lower()

                # Only purchases (not grants, sales, tax withholding)
                if "purchase" not in tx_text and "purchase" not in tx_type:
                    continue
                if "sale" in tx_text or "grant" in tx_text or "award" in tx_text:
                    continue

                value = float(row.get("Value", 0) or 0)
                if value < 100_000:
                    continue

                # Date check
                try:
                    start_date = row.get("Start Date")
                    if start_date is None:
                        continue
                    if hasattr(start_date, 'tzinfo') and start_date.tzinfo is None:
                        import pandas as pd
                        start_dt = pd.Timestamp(start_date).tz_localize("UTC")
                    else:
                        start_dt = pd.Timestamp(start_date).tz_convert("UTC")
                    if start_dt < pd.Timestamp(cutoff):
                        continue
                    date_str = start_dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = str(row.get("Start Date", ""))

                insider_name = str(row.get("Insider", "Unknown"))
                position = str(row.get("Position", ""))
                shares = int(row.get("Shares", 0) or 0)

                key = f"yf_ins:{ticker}:{insider_name}:{date_str}:{value:.0f}"
                if is_seen(cache, key):
                    continue

                # Determine priority
                pos_lower = position.lower()
                is_high_priority = any(t in pos_lower for t in HIGH_PRIORITY_TITLES)
                priority_tag = "🔴 HIGH SIGNAL" if is_high_priority else "📋"

                alerts.append({
                    "type": "insider_buy",
                    "key": key,
                    "ticker": ticker,
                    "direction": "long",
                    "message": (
                        f"{priority_tag} INSIDER BUY — {ticker} | {date_str}\n"
                        f"👤 {insider_name} ({position})\n"
                        f"📊 Purchased {shares:,} shares | Value: ${value:,.0f}\n"
                        f"🔗 https://finviz.com/quote.ashx?t={ticker}\n"
                        f"— Cooper 🦅 | Whale Tracker (SEC Form 4)"
                    ),
                })
                mark_seen(cache, key)
                print(f"  [{ticker}] {insider_name} ({position}) bought ${value:,.0f}")

        except Exception as e:
            print(f"  [{ticker}] yfinance error: {e}")
            continue

    return alerts


def check_institutional_changes(cache):
    """Detect significant institutional holder changes via yfinance.

    Flags: new large positions or >5% change in holdings from top institutions.
    Source: yfinance institutional_holders — completely free.
    """
    alerts = []

    SIGNAL_INSTITUTIONS = {
        "soros", "druckenmiller", "berkshire", "pershing", "appaloosa",
        "tiger", "point72", "viking", "third point", "duquesne",
        "bridgewater", "citadel", "renaissance"
    }

    INST_CACHE_KEY = "inst_holders_snapshot"
    prev_snapshot = cache.get(INST_CACHE_KEY, {})

    try:
        import yfinance as yf
    except ImportError:
        return alerts

    new_snapshot = {}
    for ticker in WATCHLIST[:12]:  # Limit to avoid rate throttling
        try:
            t = yf.Ticker(ticker)
            ih = t.institutional_holders
            if ih is None or ih.empty:
                continue

            current = {}
            for _, row in ih.iterrows():
                holder = str(row.get("Holder", ""))
                pct = float(row.get("pctHeld", 0) or 0)
                current[holder] = pct

                # Check if it's a tracked guru institution
                holder_lower = holder.lower()
                if any(sig in holder_lower for sig in SIGNAL_INSTITUTIONS):
                    prev_pct = prev_snapshot.get(ticker, {}).get(holder, 0)
                    change = pct - prev_pct
                    if abs(change) > 0.005:  # >0.5% change
                        key = f"inst:{ticker}:{holder}:{pct:.4f}"
                        if not is_seen(cache, key):
                            direction = "increased" if change > 0 else "reduced"
                            alerts.append({
                                "type": "institutional",
                                "key": key,
                                "ticker": ticker,
                                "direction": "long" if change > 0 else "short",
                                "message": (
                                    f"🏦 INSTITUTIONAL CHANGE — {ticker}\n"
                                    f"🏛️ {holder} {direction} position: {pct*100:.2f}% ({change*100:+.2f}%)\n"
                                    f"🔗 https://finviz.com/quote.ashx?t={ticker}\n"
                                    f"— Cooper 🦅 | Whale Tracker (Institutional)"
                                ),
                            })
                            mark_seen(cache, key)

            new_snapshot[ticker] = current
        except Exception as e:
            print(f"  [{ticker}] institutional error: {e}")

    cache[INST_CACHE_KEY] = new_snapshot
    return alerts


def main():
    print(f"🐋 Whale Tracker | {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    cache = load_cache()

    all_alerts = []

    print("\n[1/5] Congressional trades (manual reminder)...")
    congressional = check_congressional_trades(cache)
    print(f"  Found: {len(congressional)}")
    all_alerts.extend(congressional)

    print("\n[2/5] Insider buys (yfinance SEC Form 4 — free)...")
    yf_insider = check_yfinance_insider_buys(cache)
    print(f"  Found: {len(yf_insider)}")
    all_alerts.extend(yf_insider)

    print("\n[3/5] Insider Form 4 RSS feeds...")
    insider = check_insider_form4(cache)
    print(f"  Found: {len(insider)}")
    all_alerts.extend(insider)

    print("\n[4/5] Institutional holder changes (yfinance — free)...")
    institutional = check_institutional_changes(cache)
    print(f"  Found: {len(institutional)}")
    all_alerts.extend(institutional)

    print("\n[5/5] Unusual options flow (Finnhub)...")
    options = check_unusual_options(cache)
    print(f"  Found: {len(options)}")
    all_alerts.extend(options)

    print(f"\n📊 Total alerts: {len(all_alerts)}")

    for alert in all_alerts:
        print(f"\n🚨 {alert['type'].upper()}: {alert.get('ticker','?')}")
        print(alert['message'])
        channel = alert.get("channel_override", DISCORD_WAR_ROOM)
        post_discord(channel, alert['message'])

    if not all_alerts:
        print("✅ No new whale activity detected.")

    cache["last_run"] = datetime.now(timezone.utc).isoformat()
    save_cache(cache)
    print("\nDone.")


if __name__ == "__main__":
    main()
