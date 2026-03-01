#!/usr/bin/env python3
"""
guru_tracker.py — Track top traders, hedge funds, and politicians.
Detects new 13F positions, congressional trades by known high-alpha names,
and applies guru score bonuses.

Data sources:
  - SEC EDGAR 13F filings (quarterly)
  - House/Senate stock watcher APIs (STOCK Act)
  - data/top_traders.json (curated profiles)

Score bonuses applied via logs/guru_signals.json → consumed by get_market_data.py
"""

import sys
import os
import json
import requests
import feedparser
import calendar
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv
load_dotenv(REPO / ".env")

PROFILES_FILE = REPO / "data" / "top_traders.json"
CACHE_FILE = REPO / "logs" / "guru_cache.json"
SIGNALS_FILE = REPO / "logs" / "guru_signals.json"

DISCORD_WAR_ROOM = "1469763123010342953"
DISCORD_BREAKING = "1477247545322246198"

WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AMD", "TSLA",
    "PLTR", "CRWD", "ARM", "MSTR", "XOM", "CVX", "COP", "SLB",
    "LMT", "RTX", "NOC", "JPM", "GS", "BAC", "LLY", "PFE", "MRNA",
    "GLD", "TLT", "QQQ", "SPY", "IWM"
]


def load_profiles():
    try:
        return json.loads(PROFILES_FILE.read_text())
    except Exception as e:
        print(f"[profiles] Error loading: {e}")
        return {"hedge_funds": [], "politicians": [], "action_multipliers": {}, "alpha_tiers": {}}


def compute_bonus(alpha_score: float, action: str, profiles: dict) -> float:
    """
    Compute score bonus dynamically from alpha_score + action_multiplier.
    Formula: bonus = alpha_score * action_multiplier, capped at 0.95.
    No hardcoded names — add any manager with an alpha_score and bonuses auto-derive.
    """
    multipliers = profiles.get("action_multipliers", {})
    multiplier = multipliers.get(action, 0.75)  # default: 0.75 for unknown actions
    bonus = round(alpha_score * multiplier, 2)
    return min(0.95, max(0.0, bonus))


def get_alpha_tier(alpha_score: float, profiles: dict) -> dict:
    """Return tier metadata for a given alpha score."""
    tiers = profiles.get("alpha_tiers", {})
    for tier_name in ("elite", "high", "mid", "low"):
        t = tiers.get(tier_name, {})
        if alpha_score >= t.get("min", 0):
            return {"tier": tier_name, **t}
    return {"tier": "low", "label": "Low alpha", "vip": False}


def load_cache():
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except:
        pass
    return {"seen": [], "last_13f_check": None}


def save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def load_signals():
    try:
        if SIGNALS_FILE.exists():
            return json.loads(SIGNALS_FILE.read_text())
    except:
        pass
    return {}


def save_signals(signals):
    SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_FILE.write_text(json.dumps(signals, indent=2))


def post_discord(channel_id, message):
    import subprocess
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        try:
            subprocess.run(
                ["openclaw", "message", "send", "--channel", "discord",
                 "--target", channel_id, "--message", chunk],
                capture_output=True, timeout=15
            )
        except Exception as e:
            print(f"[discord] Error: {e}")


def check_political_trades(profiles, cache, signals):
    """Check congressional trades, flag high-alpha politicians."""
    alerts = []
    politicians = {p["stock_watcher_id"]: p for p in profiles.get("politicians", [])
                   if p.get("stock_watcher_id")}
    # Generic congressional alpha: find the catch-all entry
    generic_pol = next((p for p in profiles.get("politicians", []) if p.get("id") == "congress_generic_buy"), {})
    generic_alpha = generic_pol.get("alpha_score", 0.55)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    sources = [
        ("House", "https://housestockwatcher.com/api"),
        ("Senate", "https://senatestockwatcher.com/api"),
    ]

    for chamber, url in sources:
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "CooperCorp/1.0"})
            if r.status_code != 200:
                print(f"[{chamber}] HTTP {r.status_code}")
                continue
            data = r.json()
            transactions = data if isinstance(data, list) else data.get("data", [])

            for tx in transactions[:100]:
                ticker = tx.get("ticker", "").upper().strip()
                if not ticker or ticker == "--":
                    continue

                name = tx.get("representative", tx.get("senator", "Unknown"))
                tx_type = tx.get("type", "").lower()
                date_str = tx.get("transaction_date", tx.get("disclosure_date", ""))
                amount = tx.get("amount", "N/A")

                key = f"political:{chamber}:{name}:{ticker}:{date_str}:{tx_type}"
                if key in cache.get("seen", []):
                    continue

                # Parse date
                try:
                    tx_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if tx_date < cutoff:
                        continue
                except:
                    pass

                is_buy = "purchase" in tx_type or "buy" in tx_type
                if not is_buy:
                    continue

                # Determine if VIP politician
                is_vip = any(p_name.lower() in name.lower() for p_name in politicians.keys())
                vip_data = None
                for p_name, p_data in politicians.items():
                    if p_name.lower() in name.lower():
                        vip_data = p_data
                        break

                # Score bonus — formula-driven: alpha_score * action_multiplier
                if vip_data:
                    bonus = compute_bonus(vip_data.get("alpha_score", generic_alpha),
                                         "congressional_purchase", profiles)
                else:
                    bonus = compute_bonus(generic_alpha, "congressional_purchase", profiles)

                # Update signals
                if ticker in WATCHLIST or is_vip:
                    if ticker not in signals:
                        signals[ticker] = {"guru_bonus": 0, "reasons": []}
                    signals[ticker]["guru_bonus"] = max(signals[ticker]["guru_bonus"], bonus)
                    signals[ticker]["reasons"].append(f"{name} bought {amount} on {date_str}")
                    signals[ticker]["updated"] = datetime.now(timezone.utc).isoformat()

                    vip_tag = f" ⭐ HIGH ALPHA ({vip_data['alpha_score']})" if vip_data else ""
                    msg = (
                        f"🏛️ POLITICAL TRADE{vip_tag}\n"
                        f"👤 {name} ({chamber})\n"
                        f"🟢 BUY {ticker} | {amount}\n"
                        f"📅 {date_str}\n"
                        f"⚡ Score bonus: +{bonus} | Signal: LONG {ticker}\n"
                        f"— Cooper 🦅 | Guru Tracker"
                    )
                    alerts.append({"key": key, "message": msg, "ticker": ticker, "bonus": bonus, "is_vip": is_vip})
                    cache.setdefault("seen", []).append(key)

        except Exception as e:
            print(f"[{chamber}] Error: {e}")

    return alerts


def check_13f_changes(profiles, cache, signals):
    """Check SEC EDGAR for new 13F filings from top funds."""
    alerts = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)  # 13F lag window

    for fund in profiles.get("hedge_funds", []):
        cik = fund.get("sec_cik")
        if not cik:
            continue

        try:
            # Get recent 13F filings
            url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
            r = requests.get(url, timeout=8, headers={"User-Agent": "CooperCorp research@coopercorp.ai"})
            if r.status_code != 200:
                continue

            data = r.json()
            filings = data.get("filings", {}).get("recent", {})
            forms = filings.get("form", [])
            dates = filings.get("filingDate", [])
            accessions = filings.get("accessionNumber", [])

            # Find most recent 13F
            for i, form in enumerate(forms):
                if form in ("13F-HR", "13F-HR/A"):
                    filing_date = dates[i] if i < len(dates) else ""
                    acc = accessions[i] if i < len(accessions) else ""

                    key = f"13f:{fund['id']}:{acc}"
                    if key in cache.get("seen", []):
                        break

                    # Check if recent
                    try:
                        fd = datetime.strptime(filing_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        if fd < cutoff:
                            break
                    except:
                        break

                    # New 13F detected!
                    manager = fund["manager"]
                    alpha = fund["alpha_score"]
                    key_sectors = ", ".join(fund.get("key_sectors", [])[:5])

                    msg = (
                        f"📊 NEW 13F FILING — {fund['name']}\n"
                        f"👤 {manager} | Alpha: {alpha}\n"
                        f"📅 Filed: {filing_date}\n"
                        f"🎯 Known positions: {key_sectors}\n"
                        f"⚡ Review for new/exited positions\n"
                        f"🔗 https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F&dateb=&owner=include&count=5\n"
                        f"— Cooper 🦅 | Guru Tracker"
                    )
                    alerts.append({"key": key, "message": msg, "fund": fund["id"]})
                    cache.setdefault("seen", []).append(key)

                    # Apply bonus — formula: alpha_score * new_position multiplier
                    bonus = compute_bonus(alpha, "new_position", profiles)
                    tier = get_alpha_tier(alpha, profiles)
                    for ticker in fund.get("key_sectors", []):
                        if ticker in WATCHLIST:
                            if ticker not in signals:
                                signals[ticker] = {"guru_bonus": 0, "reasons": []}
                            signals[ticker]["guru_bonus"] = max(signals[ticker]["guru_bonus"], bonus)
                            signals[ticker]["reasons"].append(
                                f"New 13F: {manager} ({tier['label']}) filed {filing_date} | bonus +{bonus}"
                            )
                            signals[ticker]["updated"] = datetime.now(timezone.utc).isoformat()
                    break

        except Exception as e:
            print(f"[13F:{fund['id']}] Error: {e}")

    return alerts


def check_guru_rss(profiles, cache, signals):
    """Check RSS feeds for guru news (new positions, public comments)."""
    alerts = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)

    # GuruFocus RSS + Google News alerts for top managers
    managers = ["Druckenmiller", "Ackman", "Tepper", "Burry", "Buffett", "Pelosi"]
    feeds = [
        ("GuruFocus-New", "https://www.gurufocus.com/news/index.php?action=index&rss=true"),
    ]

    for name, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "")
                link = entry.get("link", "")

                # Check if mentions a top guru + our watchlist
                matched_guru = next((g for g in managers if g.lower() in title.lower()), None)
                matched_ticker = next((t for t in WATCHLIST if t in title.upper()), None)

                if not matched_guru or not matched_ticker:
                    continue

                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_dt = datetime.fromtimestamp(calendar.timegm(pub), tz=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                key = f"guru_rss:{title[:60]}"
                if key in cache.get("seen", []):
                    continue

                msg = (
                    f"📰 GURU SIGNAL — {matched_guru} + {matched_ticker}\n"
                    f"{title[:120]}\n"
                    f"⚡ Watch {matched_ticker}\n"
                    f"🔗 {link}\n"
                    f"— Cooper 🦅 | Guru Tracker"
                )
                alerts.append({"key": key, "message": msg, "ticker": matched_ticker})
                cache.setdefault("seen", []).append(key)

        except Exception as e:
            print(f"[{name}] Error: {e}")

    return alerts


def print_profiles_summary(profiles):
    """Print a summary of loaded profiles."""
    funds = profiles.get("hedge_funds", [])
    pols = profiles.get("politicians", [])
    print(f"\n📋 Loaded {len(funds)} hedge fund profiles + {len(pols)} politician profiles")
    print(f"Top funds: {', '.join(f['manager'] for f in funds[:5])}")
    print(f"Top politicians: {', '.join(p['name'] for p in pols[:3])}")


def main():
    print(f"🧠 Guru Tracker | {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")

    profiles = load_profiles()
    cache = load_cache()
    signals = load_signals()

    print_profiles_summary(profiles)

    all_alerts = []

    print("\n[1/3] Political trades (STOCK Act)...")
    political = check_political_trades(profiles, cache, signals)
    print(f"  Found: {len(political)}")
    all_alerts.extend(political)

    print("\n[2/3] 13F new filings...")
    filings = check_13f_changes(profiles, cache, signals)
    print(f"  Found: {len(filings)}")
    all_alerts.extend(filings)

    print("\n[3/3] Guru RSS signals...")
    rss = check_guru_rss(profiles, cache, signals)
    print(f"  Found: {len(rss)}")
    all_alerts.extend(rss)

    print(f"\n📊 Total alerts: {len(all_alerts)}")

    for alert in all_alerts:
        print(f"\n🚨 {alert.get('ticker', alert.get('fund', '?'))}")
        print(alert["message"])
        post_discord(DISCORD_WAR_ROOM, alert["message"])
        # VIP (Pelosi, Druckenmiller) also post to breaking news
        elite_threshold = profiles.get("alpha_tiers", {}).get("elite", {}).get("min", 0.85)
        if alert.get("is_vip") or alert.get("bonus", 0) >= elite_threshold:
            post_discord(DISCORD_BREAKING, alert["message"])

    if not all_alerts:
        print("✅ No new guru signals.")

    # Clean up old signals (>7 days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    signals = {k: v for k, v in signals.items()
               if v.get("updated", "9999") > cutoff}

    cache["last_run"] = datetime.now(timezone.utc).isoformat()
    cache["seen"] = cache.get("seen", [])[-1000:]
    save_cache(cache)
    save_signals(signals)

    print(f"\n✅ Guru signals active: {list(signals.keys())}")
    print("Done.")


if __name__ == "__main__":
    main()
