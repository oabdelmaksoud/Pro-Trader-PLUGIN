#!/usr/bin/env python3
"""
ticker_news_scanner.py — Real-time ticker-specific news scanner.

Runs every 2 minutes. Checks Finnhub company-news for 15 watchlist tickers.
No LLM — pure keyword classification. Zero extra token cost.

Closes the gap between scheduled scans (30-90 min) and breaking news (macro only).
Stock-specific catalysts now trigger trade_gate.py within ~2 minutes.

Catalyst Tiers:
  CATALYST_A (score boost +1.2): Earnings beat/miss, M&A, FDA approval/rejection,
                                   analyst upgrade/downgrade from major bank,
                                   CEO departure, activist investor entry
  CATALYST_B (score boost +0.6): Product launch, partnership, contract win,
                                   index inclusion, secondary offering
  CATALYST_C (score boost +0.3): Analyst initiation, price target change (minor),
                                   conference presentation

Only CATALYST_A and CATALYST_B fire news_trade_trigger.py.
CATALYST_C is logged but does not trigger trades.
"""
import sys, os, json, re, time, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

import requests

# ─── Config ────────────────────────────────────────────────────────────────────

WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META",
    "AMZN", "AMD", "TSLA", "PLTR", "CRWD",
    "ARM",  "MSTR", "XOM",  "CVX",  "LMT",
    "RTX",  "NOC",  "JPM",  "GS",   "SPY"
]

SCAN_WINDOW_MIN = 4          # look back 4 minutes (same as breaking news)
DEDUP_FILE = REPO / "logs" / "ticker_news_dedup.json"
WAR_ROOM    = "1469763123010342953"
PAPER_TRADES = "1468597633756037385"

# ─── Keyword Classifiers ───────────────────────────────────────────────────────

CATALYST_A_LONG = [
    r"earnings? beat", r"eps beat", r"revenue beat", r"raised? guidance",
    r"better.than.expected", r"acquisition", r"merger", r"acqui",
    r"fda approv", r"breakthrough therapy", r"positive (phase|data|results|trial)",
    r"activist investor", r"stake.in", r"buys? \d+%", r"taken? private",
    r"buyback", r"share repurchase", r"special dividend",
    r"major contract", r"pentagon contract", r"dod contract",
    r"ceo (steps down|resign|replac)", r"strategic (review|alternatives)",
]
CATALYST_A_SHORT = [
    r"earnings? miss", r"eps miss", r"revenue miss", r"lowered? guidance",
    r"worse.than.expected", r"missed? (estimates?|expectations?)",
    r"fda reject", r"complete response letter", r"clinical (hold|failure|halt)",
    r"negative (phase|data|results|trial)", r"fraud", r"sec investi",
    r"class action", r"restatement", r"accounting irreg",
    r"downgrad", r"sell rating", r"price target cut",
    r"ceo (fired|termin)", r"whistleblower",
]
CATALYST_B_LONG = [
    r"partnership", r"collaboration", r"joint venture", r"license agreement",
    r"product launch", r"new product", r"major customer",
    r"index inclusion", r"added to (s&p|nasdaq|russell|dow)",
    r"upgrad", r"buy rating", r"overweight", r"outperform",
    r"price target (raised|increased|hike)",
    r"contract win", r"awarded",
]
CATALYST_B_SHORT = [
    r"price target (cut|lower|reduc)",
    r"underweight", r"underperform", r"market perform",
    r"secondary offering", r"dilutive", r"equity offering",
    r"removed from (s&p|nasdaq|russell)",
]
CATALYST_C = [
    r"initiates? coverage", r"analyst note", r"conference presentation",
    r"investor day", r"price target", r"neutral rating",
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_dedup() -> dict:
    if DEDUP_FILE.exists():
        try:
            return json.loads(DEDUP_FILE.read_text())
        except:
            pass
    return {}

def save_dedup(cache: dict):
    DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    # prune entries older than 4 hours
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    cache = {k: v for k, v in cache.items() if v > cutoff}
    DEDUP_FILE.write_text(json.dumps(cache, indent=2))

def already_seen(dedup: dict, key: str) -> bool:
    return key in dedup

def mark_seen(dedup: dict, key: str):
    dedup[key] = datetime.now(timezone.utc).isoformat()

def classify(headline: str) -> tuple[str, str]:
    """Returns (tier, direction) or (None, None) if no catalyst."""
    h = headline.lower()
    for pat in CATALYST_A_LONG:
        if re.search(pat, h):
            return "CATALYST_A", "long"
    for pat in CATALYST_A_SHORT:
        if re.search(pat, h):
            return "CATALYST_A", "short"
    for pat in CATALYST_B_LONG:
        if re.search(pat, h):
            return "CATALYST_B", "long"
    for pat in CATALYST_B_SHORT:
        if re.search(pat, h):
            return "CATALYST_B", "short"
    for pat in CATALYST_C:
        if re.search(pat, h):
            return "CATALYST_C", "neutral"
    return None, None

def post_discord(channel_id: str, msg: str):
    try:
        subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target", channel_id,
             "--message", msg],
            capture_output=True, timeout=10
        )
    except Exception as e:
        print(f"Discord post failed: {e}")

def trigger_trade(ticker: str, tier: str, direction: str, headline: str, url: str):
    """Call news_trade_trigger.py to score and potentially execute a trade."""
    tier_map = {"CATALYST_A": "TIER1", "CATALYST_B": "TIER2"}
    t = tier_map.get(tier, "TIER2")
    try:
        result = subprocess.run(
            ["python3", str(REPO / "scripts" / "news_trade_trigger.py"),
             "--tickers", ticker,
             "--tier", t,
             "--headline", headline[:200],
             "--category", "CATALYST",
             "--direction", direction],
            capture_output=True, text=True, timeout=60, cwd=str(REPO)
        )
        print(result.stdout[-500:] if result.stdout else "(no output)")
        if result.returncode != 0 and result.stderr:
            print(f"WARN: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"WARN: news_trade_trigger timed out for {ticker}")
    except Exception as e:
        print(f"WARN: trigger failed for {ticker}: {e}")

def is_market_hours() -> bool:
    """Check if we're in trading hours (9:35 AM–2:15 PM ET)."""
    import pytz
    et = pytz.timezone("America/New_York")
    now = datetime.now(et).time()
    from datetime import time as dtime
    return dtime(9, 35) <= now <= dtime(14, 15)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key:
        print("ERROR: FINNHUB_API_KEY not set")
        return

    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(minutes=SCAN_WINDOW_MIN)).timestamp())
    now_str = datetime.now().strftime("%H:%M ET")

    dedup = load_dedup()
    triggered = []
    logged = []

    print(f"[ticker_news_scanner] {now_str} | Scanning {len(WATCHLIST)} tickers | market_hours={is_market_hours()}")

    for ticker in WATCHLIST:
        try:
            r = requests.get(
                f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
                f"&from=2020-01-01&to=2099-01-01&token={api_key}",
                timeout=4
            )
            if r.status_code != 200:
                continue
            articles = r.json() or []
        except Exception as e:
            print(f"  [{ticker}] fetch error: {e}")
            continue

        for article in articles[:5]:
            if article.get("datetime", 0) < cutoff_ts:
                continue
            headline = article.get("headline", "").strip()
            url = article.get("url", "")
            if not headline:
                continue

            dedup_key = f"{ticker}:{headline[:80]}"
            if already_seen(dedup, dedup_key):
                continue

            tier, direction = classify(headline)
            if tier is None:
                continue

            mark_seen(dedup, dedup_key)
            logged.append(f"  [{ticker}] {tier} ({direction}) — {headline[:80]}")

            if tier in ("CATALYST_A", "CATALYST_B") and is_market_hours():
                print(f"  🔥 {ticker} {tier} {direction}: {headline[:60]}")
                trigger_trade(ticker, tier, direction, headline, url)
                triggered.append(ticker)

                # Post to war-room
                emoji = "🚨" if tier == "CATALYST_A" else "⚡"
                arrow = "📈" if direction == "long" else "📉"
                post_discord(WAR_ROOM,
                    f"{emoji} TICKER CATALYST — {ticker} | {now_str}\n"
                    f"{arrow} {headline}\n"
                    f"Tier: {tier} | Direction: {direction.upper()}\n"
                    f"🔗 {url}\n"
                    f"⚡ Trade trigger sent — Cooper 🦅"
                )
            elif tier in ("CATALYST_A", "CATALYST_B") and not is_market_hours():
                print(f"  [{ticker}] {tier} found but outside market hours — logged only")
            # CATALYST_C: log only, no trade

        time.sleep(0.08)  # ~80ms between tickers, stays under Finnhub free tier rate limit

    save_dedup(dedup)

    if triggered:
        print(f"\n✅ Triggered trades for: {', '.join(triggered)}")
    else:
        print(f"\nSILENT PASS — 0 catalysts triggered | {len(logged)} CATALYST_C logged")

    for line in logged:
        print(line)

if __name__ == "__main__":
    main()
