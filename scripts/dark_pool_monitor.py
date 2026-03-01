"""
dark_pool_monitor.py — Dark pool and block trade monitor
Runs every 30 min during market hours.
Detects large single trades (>$1M) via Finnhub tick data.
Gracefully skips if tick data unavailable (free tier limit).
"""

import sys
import json
import subprocess
import os
from pathlib import Path
from datetime import datetime, date

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass

DISCORD_CHANNEL = "1469763123010342953"
LOGS_DIR = REPO / "logs"
LOGS_DIR.mkdir(exist_ok=True)
CACHE_FILE = LOGS_DIR / "dark_pool_cache.json"

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")

WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AMD", "TSLA",
    "PLTR", "CRWD", "ARM", "MSTR", "XOM", "CVX", "LMT", "RTX", "JPM", "LLY", "PFE"
]

BLOCK_THRESHOLD = 1_000_000  # $1M


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[dark_pool_monitor] Discord post failed: {e}")


def load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception:
        pass
    return {"seen_trades": {}}


def save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception as e:
        print(f"[dark_pool_monitor] Cache save failed: {e}")


def fetch_tick_data(ticker: str, today_str: str) -> list:
    if not requests or not FINNHUB_KEY:
        return []
    try:
        url = (
            f"https://finnhub.io/api/v1/stock/tick"
            f"?symbol={ticker}&date={today_str}&limit=100&skip=0&token={FINNHUB_KEY}"
        )
        resp = requests.get(url, timeout=15)
        if resp.status_code == 429:
            print(f"[dark_pool_monitor] Rate limit hit for {ticker} — skipping")
            return []
        resp.raise_for_status()
        data = resp.json()
        prices = data.get("p", [])
        volumes = data.get("v", [])
        timestamps = data.get("t", [])
        trades = []
        for i in range(min(len(prices), len(volumes))):
            ts = timestamps[i] if i < len(timestamps) else 0
            trades.append({"price": prices[i], "volume": volumes[i], "timestamp": ts})
        return trades
    except Exception as e:
        print(f"[dark_pool_monitor] Tick fetch failed for {ticker}: {e}")
        return []


def main():
    today_str = date.today().strftime("%Y-%m-%d")
    cache = load_cache()
    seen = cache.get("seen_trades", {})

    for ticker in WATCHLIST:
        try:
            trades = fetch_tick_data(ticker, today_str)
            if not trades:
                continue

            for trade in trades:
                price = trade.get("price", 0)
                volume = trade.get("volume", 0)
                ts = trade.get("timestamp", 0)
                trade_value = price * volume

                if trade_value >= BLOCK_THRESHOLD:
                    trade_id = f"{ticker}_{ts}_{price}_{volume}"
                    if trade_id in seen.get(ticker, []):
                        continue

                    value_m = trade_value / 1_000_000
                    msg = (
                        f"🌊 DARK POOL PRINT — {ticker}\n"
                        f"💰 ${value_m:.2f}M block trade @ ${price:.2f}\n"
                        f"📊 {int(volume):,} shares\n"
                        f"⚡ Whale accumulation signal\n"
                        f"— Cooper 🦅"
                    )
                    print(msg)
                    post_to_discord(msg)

                    if ticker not in seen:
                        seen[ticker] = []
                    seen[ticker].append(trade_id)
        except Exception as e:
            print(f"[dark_pool_monitor] Error processing {ticker}: {e}")

    cache["seen_trades"] = seen
    cache["last_run"] = datetime.utcnow().isoformat()
    save_cache(cache)


if __name__ == "__main__":
    main()
