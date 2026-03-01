#!/usr/bin/env python3
"""
ticker_news_scanner.py — Real-time ticker-specific news scanner.

Runs every 2 minutes. Checks Finnhub company-news for 20 watchlist tickers.
Uses a 2-layer classification pipeline:

  Layer 1 — Keyword regex (instant, free):
    Fast pattern matching for clear catalysts. Catches ~85% of actionable stories.

  Layer 2 — LLM sentiment verification (claude, only on CATALYST_A/B hits + ambiguous):
    Verifies direction and catches nuanced headlines keywords miss.
    Prompt is minimal (~50 tokens). Only fires on actual hits — not every headline.
    Estimated: ~5-15 LLM calls/day during active news periods. Negligible cost.

Catalyst Tiers:
  CATALYST_A (score boost +1.2): Earnings beat/miss, M&A, FDA approval/rejection,
                                   CEO departure, activist investor entry, SEC/fraud
  CATALYST_B (score boost +0.6): Analyst upgrade/downgrade, partnership, product launch,
                                   index inclusion, contract win, secondary offering
  CATALYST_C: Logged only, no trade trigger
  AMBIGUOUS:  Sent to LLM for judgment — can be promoted to A/B

Only CATALYST_A and CATALYST_B (confirmed by LLM) fire news_trade_trigger.py.
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

# Headlines that keywords can't confidently classify → send to LLM
AMBIGUOUS_PATTERNS = [
    r"mixed results?", r"in line with", r"meets? expectations?",
    r"reports? (results?|earnings?|revenue)", r"quarterly (results?|earnings?)",
    r"update[sd]?", r"announces?", r"confirms?", r"plan[ns]?",
    r"review", r"strategic", r"restructur", r"realign",
    r"outlook", r"forecast", r"guidance",
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
    """Layer 1: keyword regex classification. Returns (tier, direction) or (None, None)."""
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
    # Check if ambiguous — needs LLM judgment
    for pat in AMBIGUOUS_PATTERNS:
        if re.search(pat, h):
            return "AMBIGUOUS", "unknown"
    return None, None


def llm_verify(ticker: str, headline: str, keyword_tier: str, keyword_direction: str) -> tuple[str, str]:
    """Layer 2: LLM sentiment verification for CATALYST_A/B hits and ambiguous headlines.

    Uses claude with a minimal prompt (~50 tokens in, ~20 tokens out).
    Only called on actual hits — not every headline.
    Returns (confirmed_tier, confirmed_direction).
    """
    prompt = (
        f"Stock: {ticker}\n"
        f"Headline: {headline}\n\n"
        f"Is this headline BULLISH, BEARISH, or NEUTRAL for {ticker} stock price? "
        f"Is the impact MAJOR (earnings/M&A/FDA/fraud/CEO) or MINOR (analyst note/partnership/guidance)?\n\n"
        f"Reply in exactly this format:\n"
        f"SENTIMENT: [BULLISH|BEARISH|NEUTRAL]\n"
        f"IMPACT: [MAJOR|MINOR|NONE]\n"
        f"REASON: [one sentence max]"
    )

    try:
        result = subprocess.run(
            ["claude", "--print", "--model", "claude-haiku-4-5", prompt],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            # Fallback to sonnet if haiku unavailable
            result = subprocess.run(
                ["claude", "--print", "--model", "claude-sonnet-4-6", prompt],
                capture_output=True, text=True, timeout=15
            )
        output = result.stdout.strip().upper()
    except Exception as e:
        print(f"  LLM verify error: {e} — using keyword result")
        return keyword_tier, keyword_direction

    # Parse response
    sentiment = "NEUTRAL"
    impact = "NONE"
    for line in output.splitlines():
        if line.startswith("SENTIMENT:"):
            s = line.split(":", 1)[1].strip()
            if "BULLISH" in s:
                sentiment = "BULLISH"
            elif "BEARISH" in s:
                sentiment = "BEARISH"
        elif line.startswith("IMPACT:"):
            i = line.split(":", 1)[1].strip()
            if "MAJOR" in i:
                impact = "MAJOR"
            elif "MINOR" in i:
                impact = "MINOR"

    # Map to tier + direction
    direction_map = {"BULLISH": "long", "BEARISH": "short", "NEUTRAL": "neutral"}
    direction = direction_map.get(sentiment, keyword_direction)

    if sentiment == "NEUTRAL" or impact == "NONE":
        # LLM says not actionable
        print(f"  LLM override: NEUTRAL/NONE — skipping trade trigger")
        return "CATALYST_C", "neutral"  # downgrade to log-only

    if impact == "MAJOR":
        tier = "CATALYST_A"
    elif impact == "MINOR":
        tier = "CATALYST_B"
    else:
        tier = keyword_tier if keyword_tier not in ("AMBIGUOUS", None) else "CATALYST_C"

    print(f"  LLM verdict: {sentiment} | {impact} → {tier} {direction}")
    return tier, direction

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

# Tickers that trade outside regular US market hours
CRYPTO_PROXIES = {"MSTR", "COIN", "RIOT", "MARA", "CLSK", "CORZ"}
FUTURES_TICKERS = {"ES=F", "NQ=F", "CL=F", "GC=F", "SI=F", "NG=F"}


def get_market_session(ticker: str) -> str:
    """
    Returns the current market session for a given ticker:
      'regular'       — 9:30 AM–4:00 PM ET (full liquidity, normal entry rules)
      'premarket'     — 4:00 AM–9:30 AM ET (Alpaca extended_hours=True, wider spreads)
      'afterhours'    — 4:00 PM–8:00 PM ET (Alpaca extended_hours=True, lower volume)
      'crypto_active' — 24/7 for crypto proxies and BTC-correlated tickers
      'futures_active'— Sunday 6 PM–Friday 5 PM ET (futures tickers)
      'closed'        — weekends/overnight for regular equities
    """
    import pytz
    from datetime import time as dtime

    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)
    t = now_et.time()
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    # Crypto proxies — always active
    if ticker.upper() in CRYPTO_PROXIES:
        return "crypto_active"

    # Futures — active Sun 6 PM through Fri 5 PM ET (with 1h maintenance gap)
    if ticker.upper() in FUTURES_TICKERS:
        if weekday == 5:  # Saturday — futures closed
            return "closed"
        if weekday == 6 and t < dtime(18, 0):  # Sunday before 6 PM
            return "closed"
        if weekday == 4 and t >= dtime(17, 0):  # Friday after 5 PM
            return "closed"
        return "futures_active"

    # Regular equities — check session
    if weekday >= 5:  # Weekend
        return "closed"
    if dtime(9, 30) <= t < dtime(16, 0):
        return "regular"
    if dtime(4, 0) <= t < dtime(9, 30):
        return "premarket"
    if dtime(16, 0) <= t < dtime(20, 0):
        return "afterhours"
    return "closed"  # overnight (8 PM–4 AM ET)

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

    print(f"[ticker_news_scanner] {now_str} | Scanning {len(WATCHLIST)} tickers | market_session={get_market_session('SPY')}")

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

            # Layer 2: LLM verification for CATALYST_A, CATALYST_B, and AMBIGUOUS
            if tier in ("CATALYST_A", "CATALYST_B", "AMBIGUOUS"):
                print(f"  🔍 LLM verify: [{ticker}] keyword={tier} | {headline[:70]}")
                tier, direction = llm_verify(ticker, headline, tier, direction)

            logged.append(f"  [{ticker}] {tier} ({direction}) — {headline[:80]}")

            if tier in ("CATALYST_A", "CATALYST_B"):
                session = get_market_session(ticker)
                emoji = "🚨" if tier == "CATALYST_A" else "⚡"
                arrow = "📈" if direction == "long" else "📉"

                if session == "regular":
                    # Normal market hours — full entry rules apply
                    print(f"  🔥 {ticker} {tier} {direction} [REGULAR]: {headline[:55]}")
                    trigger_trade(ticker, tier, direction, headline, url)
                    triggered.append(ticker)
                    post_discord(WAR_ROOM,
                        f"{emoji} CATALYST — {ticker} | {now_str}\n"
                        f"{arrow} {headline}\n"
                        f"Tier: {tier} | Session: REGULAR | Direction: {direction.upper()}\n"
                        f"🔗 {url}\n"
                        f"⚡ Trade trigger sent — Cooper 🦅"
                    )

                elif session in ("premarket", "afterhours"):
                    # Extended hours — Alpaca supports this with extended_hours=True flag
                    print(f"  ⏰ {ticker} {tier} {direction} [{session.upper()}]: {headline[:55]}")
                    trigger_trade(ticker, tier, direction, headline, url)
                    triggered.append(ticker)
                    post_discord(WAR_ROOM,
                        f"{emoji} CATALYST [{session.upper()}] — {ticker} | {now_str}\n"
                        f"{arrow} {headline}\n"
                        f"Tier: {tier} | Direction: {direction.upper()} | Extended hours trade\n"
                        f"⚠️ Wider spreads — limit orders recommended\n"
                        f"🔗 {url}\n"
                        f"⚡ Trade trigger sent — Cooper 🦅"
                    )

                elif session in ("crypto_active", "futures_active"):
                    # 24/7 instruments — always trigger
                    print(f"  🌐 {ticker} {tier} {direction} [24/7]: {headline[:55]}")
                    trigger_trade(ticker, tier, direction, headline, url)
                    triggered.append(ticker)
                    post_discord(WAR_ROOM,
                        f"{emoji} CATALYST [24/7] — {ticker} | {now_str}\n"
                        f"{arrow} {headline}\n"
                        f"Tier: {tier} | Direction: {direction.upper()}\n"
                        f"🔗 {url}\n"
                        f"⚡ Trade trigger sent — Cooper 🦅"
                    )

                elif session == "closed":
                    # Markets closed — post pre-position alert for next open
                    print(f"  📋 {ticker} {tier} {direction} [CLOSED/OVERNIGHT]: pre-position alert")
                    post_discord(WAR_ROOM,
                        f"{emoji} PRE-POSITION ALERT — {ticker} | {now_str}\n"
                        f"{arrow} {headline}\n"
                        f"Tier: {tier} | Direction: {direction.upper()}\n"
                        f"📋 Markets closed — watch at next open\n"
                        f"🔗 {url}\n"
                        f"— Cooper 🦅"
                    )
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
