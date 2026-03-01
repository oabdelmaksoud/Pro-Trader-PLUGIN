"""
etf_flow_tracker.py — ETF fund flow tracker
Runs daily at market close.
Detects significant inflows/outflows via volume vs 30d average.
Posts sector rotation signals to Discord war-room.
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, date

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import yfinance as yf
except ImportError:
    yf = None

DISCORD_CHANNEL = "1469763123010342953"
LOGS_DIR = REPO / "logs"
LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = LOGS_DIR / "etf_flows.json"

SECTOR_ETFS = {
    "XLE": "Energy", "XLK": "Technology", "XLF": "Financials",
    "XLV": "Healthcare", "XLI": "Industrials", "XLY": "Consumer Disc",
    "XLP": "Consumer Staples", "XLU": "Utilities", "XLB": "Materials",
    "XLRE": "Real Estate", "GLD": "Gold", "TLT": "Long Bonds",
    "IWM": "Small Cap", "QQQ": "Nasdaq 100", "SPY": "S&P 500"
}

VOLUME_THRESHOLD = 2.0  # 2x average = significant flow


def post_to_discord(msg: str) -> None:
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", msg],
            timeout=30
        )
    except Exception as e:
        print(f"[etf_flow_tracker] Discord post failed: {e}")


def get_etf_data(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="31d")
        if hist.empty or len(hist) < 2:
            return {"ok": False}

        today_row = hist.iloc[-1]
        prev_row = hist.iloc[-2]
        today_vol = today_row["Volume"]
        avg_vol = hist["Volume"].iloc[:-1].mean()
        vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0
        price_change_pct = ((today_row["Close"] - prev_row["Close"]) / prev_row["Close"] * 100)

        return {
            "ok": True,
            "price": today_row["Close"],
            "price_change_pct": price_change_pct,
            "today_volume": int(today_vol),
            "avg_volume": int(avg_vol),
            "vol_ratio": vol_ratio,
        }
    except Exception as e:
        print(f"[etf_flow_tracker] Error fetching {symbol}: {e}")
        return {"ok": False}


def classify_flow(data: dict) -> str:
    if not data.get("ok"):
        return "unknown"
    vol_ratio = data.get("vol_ratio", 1.0)
    price_chg = data.get("price_change_pct", 0)
    if vol_ratio >= VOLUME_THRESHOLD:
        return "inflow" if price_chg >= 0 else "outflow"
    return "neutral"


def main():
    if yf is None:
        print("[etf_flow_tracker] yfinance not available — aborting")
        return

    today_str = date.today().strftime("%Y-%m-%d")
    results = {}
    inflows = []
    outflows = []

    for symbol, sector in SECTOR_ETFS.items():
        try:
            data = get_etf_data(symbol)
            flow = classify_flow(data)
            results[symbol] = {
                "sector": sector,
                "flow": flow,
                **{k: v for k, v in data.items() if k != "ok"},
                "updated": datetime.utcnow().isoformat()
            }
            if flow == "inflow":
                inflows.append((symbol, sector, data))
            elif flow == "outflow":
                outflows.append((symbol, sector, data))
        except Exception as e:
            print(f"[etf_flow_tracker] Error on {symbol}: {e}")

    # Sort by volume ratio
    inflows.sort(key=lambda x: x[2].get("vol_ratio", 0), reverse=True)
    outflows.sort(key=lambda x: x[2].get("vol_ratio", 0), reverse=True)

    # Build rotation narrative
    top_in_sectors = [s for _, s, _ in inflows[:3]]
    top_out_sectors = [s for _, s, _ in outflows[:3]]
    rotation = ""
    if top_out_sectors and top_in_sectors:
        rotation = f"Out of {', '.join(top_out_sectors[:2])} → Into {', '.join(top_in_sectors[:2])}"
    elif top_in_sectors:
        rotation = f"Strong inflows into {', '.join(top_in_sectors[:2])}"
    elif top_out_sectors:
        rotation = f"Broad outflows from {', '.join(top_out_sectors[:2])}"

    lines = [f"📊 ETF FLOWS — {today_str}", ""]
    if inflows:
        lines.append("📈 Top Inflows:")
        for sym, sec, data in inflows[:3]:
            pct = data.get("price_change_pct", 0)
            ratio = data.get("vol_ratio", 0)
            lines.append(f"  ↑ {sym} ({sec}): +{pct:.1f}% | {ratio:.1f}x avg vol")
    if outflows:
        lines.append("📉 Top Outflows:")
        for sym, sec, data in outflows[:3]:
            pct = data.get("price_change_pct", 0)
            ratio = data.get("vol_ratio", 0)
            lines.append(f"  ↓ {sym} ({sec}): {pct:.1f}% | {ratio:.1f}x avg vol")

    if rotation:
        lines.append(f"\n⚡ Rotation: {rotation}")
    lines.append("\n— Cooper 🦅 | ETF Flow Tracker")

    msg = "\n".join(lines)
    print(msg)
    if inflows or outflows:
        post_to_discord(msg)

    try:
        OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    except Exception as e:
        print(f"[etf_flow_tracker] Failed to write log: {e}")


if __name__ == "__main__":
    main()
