#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Signal Backtest
Replays past signals from logs/signals.jsonl against actual price data.
Shows what P&L would have been if all signals were acted on.

Usage:
  python3 scripts/backtest.py --days 30
  python3 scripts/backtest.py --scan-time 9:30
"""
import argparse, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import yfinance as yf

SIGNALS_FILE = Path(__file__).parent.parent / "logs" / "signals.jsonl"


def load_signals(days=None, scan_time=None, action=None):
    if not SIGNALS_FILE.exists():
        return []
    signals = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    with open(SIGNALS_FILE) as f:
        for line in f:
            try:
                s = json.loads(line)
                ts = s.get("timestamp", "")
                if cutoff and ts:
                    try:
                        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if t < cutoff:
                            continue
                    except Exception:
                        pass
                if scan_time and s.get("scan_time") != scan_time:
                    continue
                if action and s.get("action") != action:
                    continue
                signals.append(s)
            except Exception:
                continue
    return signals


def simulate_trade(signal):
    """Simulate what would have happened if this signal was acted on."""
    ticker = signal["ticker"]
    ts_raw = signal.get("timestamp", signal.get("ts", ""))
    date_str = ts_raw[:10] if ts_raw else __import__("datetime").date.today().isoformat()
    entry = signal.get("price_at_signal", 0)
    stop = signal.get("stop_loss", entry * 0.97)
    target = signal.get("target", entry * 1.08)
    if not entry:
        return None

    try:
        t = yf.Ticker(ticker)
        hist = t.history(start=date_str, period="5d", interval="1h")
        if hist.empty:
            return None

        result = "OPEN"
        exit_price = hist["Close"].iloc[-1]
        for _, row in hist.iterrows():
            if row["Low"] <= stop:
                exit_price = stop
                result = "STOP"
                break
            if row["High"] >= target:
                exit_price = target
                result = "TARGET"
                break

        pnl = (exit_price - entry) / entry if signal["action"] == "BUY" else (entry - exit_price) / entry
        return {"result": result, "entry": entry, "exit": exit_price, "pnl_pct": round(pnl * 100, 2)}
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--scan-time", default=None)
    parser.add_argument("--action", default="BUY")
    args = parser.parse_args()

    signals = load_signals(args.days, args.scan_time, args.action)
    if not signals:
        print(f"No {args.action} signals found in last {args.days} days")
        return

    print(f"\n📊 Backtest: {len(signals)} {args.action} signals over {args.days} days")
    if args.scan_time:
        print(f"   Filter: scan_time={args.scan_time}")
    print("-" * 50)

    results = []
    for s in signals:
        r = simulate_trade(s)
        if r:
            results.append(r)
            status = "✅" if r["pnl_pct"] > 0 else "❌"
            scan = s.get("scan_time", "?")
            print(f"{status} {s['ticker']:6s} {str(scan):5s} | entry ${s.get('price_at_signal',0):.2f} → exit ${r['exit']:.2f} | {r['result']:6s} | {r['pnl_pct']:+.1f}%")

    if results:
        wins = [r for r in results if r["pnl_pct"] > 0]
        total_pnl = sum(r["pnl_pct"] for r in results)
        print(f"\n📈 Results: {len(wins)}/{len(results)} wins ({len(wins)/len(results)*100:.0f}%) | Avg P&L: {total_pnl/len(results):+.1f}% | Total: {total_pnl:+.1f}%")
    else:
        print("No simulatable results (need price history)")


if __name__ == "__main__":
    main()
