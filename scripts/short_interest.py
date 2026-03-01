"""
short_interest.py — Short interest tracker
Runs weekly (Monday pre-market).
Fetches short float % from Finviz for watchlist tickers.
Posts top 5 most-shorted to Discord war-room.
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

DISCORD_CHANNEL = "1469763123010342953"
LOGS_DIR = REPO / "logs"
LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = LOGS_DIR / "short_interest.json"

WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AMD", "TSLA",
    "PLTR", "CRWD", "ARM", "MSTR", "XOM", "CVX", "LMT", "RTX", "JPM", "LLY", "PFE"
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[short_interest] Discord post failed: {e}")


def load_existing() -> dict:
    try:
        if OUTPUT_FILE.exists():
            return json.loads(OUTPUT_FILE.read_text())
    except Exception:
        pass
    return {}


def fetch_short_float(ticker: str) -> float | None:
    if not requests or not BeautifulSoup:
        return None
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Find "Short Float" in the snapshot table
        cells = soup.find_all("td")
        for i, cell in enumerate(cells):
            if "Short Float" in cell.get_text():
                if i + 1 < len(cells):
                    val_text = cells[i + 1].get_text(strip=True).replace("%", "")
                    try:
                        return float(val_text)
                    except ValueError:
                        return None
    except Exception as e:
        print(f"[short_interest] Finviz fetch failed for {ticker}: {e}")
    return None


def main():
    existing = load_existing()
    results = {}
    now_iso = datetime.utcnow().isoformat()

    for ticker in WATCHLIST:
        try:
            short_float = fetch_short_float(ticker)
            if short_float is None:
                # Carry forward existing data if available
                if ticker in existing:
                    results[ticker] = existing[ticker]
                continue

            prev_float = existing.get(ticker, {}).get("short_float", 0)
            rising = short_float > prev_float
            squeeze_candidate = short_float > 20 and rising
            score_bonus = 0.5 if squeeze_candidate else 0.0

            results[ticker] = {
                "short_float": short_float,
                "prev_short_float": prev_float,
                "rising": rising,
                "squeeze_candidate": squeeze_candidate,
                "score_bonus": score_bonus,
                "updated": now_iso,
            }
            print(f"[short_interest] {ticker}: {short_float:.1f}% short float (rising={rising})")
        except Exception as e:
            print(f"[short_interest] Error processing {ticker}: {e}")

    # Save results
    try:
        OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    except Exception as e:
        print(f"[short_interest] Failed to write log: {e}")

    # Post top 5 most shorted
    sorted_tickers = sorted(results.items(), key=lambda x: x[1].get("short_float", 0), reverse=True)
    top5 = sorted_tickers[:5]

    if top5:
        lines = ["📊 SHORT INTEREST REPORT — Weekly Scan", ""]
        for ticker, data in top5:
            sf = data.get("short_float", 0)
            rising = "↑" if data.get("rising") else "↓"
            squeeze = " 🔥 SQUEEZE CANDIDATE" if data.get("squeeze_candidate") else ""
            lines.append(f"{ticker}: {sf:.1f}% {rising}{squeeze}")

        lines.append("")
        lines.append("— Cooper 🦅 | Short Interest Tracker")
        msg = "\n".join(lines)
        print(msg)
        post_to_discord(msg)


if __name__ == "__main__":
    main()
