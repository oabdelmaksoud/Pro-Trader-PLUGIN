#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Signal Accuracy Dashboard
Prints a rich accuracy report across all logged signals.

Usage:
    python3 scripts/signal_accuracy.py
    python3 scripts/signal_accuracy.py --days 7
    python3 scripts/signal_accuracy.py --days 30
    python3 scripts/signal_accuracy.py --ticker NVDA
    python3 scripts/signal_accuracy.py --scan-time 9:30
    python3 scripts/signal_accuracy.py --days 7 --ticker NVDA
"""
import argparse
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tradingagents.signals.signal_logger import SignalLogger


def color(text, code):
    return f"\033[{code}m{text}\033[0m"


def green(t):  return color(t, "32")
def red(t):    return color(t, "31")
def yellow(t): return color(t, "33")
def cyan(t):   return color(t, "36")
def bold(t):   return color(t, "1")


def pct_str(val):
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%" if val <= 1.0 else f"{val:.1f}%"


def accuracy_color(acc):
    """Color accuracy based on quality."""
    pct = acc * 100 if acc <= 1.0 else acc
    if pct >= 65:
        return green(f"{pct:.0f}%")
    elif pct >= 50:
        return yellow(f"{pct:.0f}%")
    else:
        return red(f"{pct:.0f}%")


def build_insights(stats: dict, signals: list) -> list:
    """Generate actionable insights from signal accuracy data."""
    insights = []

    # Worst scan time
    worst_st = stats.get("worst_scan_time")
    if worst_st and worst_st in stats["by_scan_time"]:
        acc = stats["by_scan_time"][worst_st]["accuracy"]
        if acc < 0.50:
            insights.append(
                f"{worst_st} signals are below coin-flip ({acc*100:.0f}%) — consider disabling that window"
            )

    # Worst ticker
    worst_tk = stats.get("worst_ticker")
    if worst_tk and worst_tk in stats["by_ticker"]:
        acc = stats["by_ticker"][worst_tk]["accuracy"]
        if acc < 0.50:
            insights.append(
                f"{worst_tk} signals are unreliable ({acc*100:.0f}%) — consider removing from universe"
            )

    # Catalyst signals
    catalyst_signals = [
        s for s in signals
        if s.get("verified") and "catalyst" in (s.get("analysis_summary") or "").lower()
        and s.get("signal_correct") is not None
    ]
    if catalyst_signals:
        catalyst_accuracy = sum(1 for s in catalyst_signals if s.get("signal_correct")) / len(catalyst_signals)
        if catalyst_accuracy >= 0.70:
            insights.append(
                f"Catalyst signals have {catalyst_accuracy*100:.0f}% accuracy ({len(catalyst_signals)} signals) — prioritize these"
            )

    # Buy accuracy
    if stats.get("buy_accuracy", 0) > 0.70:
        insights.append(f"BUY signals are performing well at {stats['buy_accuracy']*100:.0f}% — maintain current thresholds")

    # Pass quality
    if stats.get("pass_quality", 0) < 0.50:
        insights.append("PASS filter is leaving money on the table — consider lowering PASS threshold")

    if not insights:
        insights.append("No critical patterns detected — system performing within expected range")

    return insights


def print_report(stats: dict, signals: list, args):
    """Print the formatted signal accuracy report."""
    total = stats["total_signals"]
    verified = stats["verified_signals"]
    pct_verified = (verified / total * 100) if total > 0 else 0

    # Count by action
    action_counts = {}
    for s in signals:
        a = s.get("action", "UNKNOWN")
        action_counts[a] = action_counts.get(a, 0) + 1

    # Avg gain/loss when correct/wrong per action
    def avg_accuracy_pct(action):
        subset = [
            s for s in signals
            if s.get("action") == action
            and s.get("verified")
            and s.get("accuracy_pct") is not None
            and s.get("signal_correct") is True
        ]
        if not subset:
            return None
        return sum(s["accuracy_pct"] for s in subset) / len(subset)

    print()
    print(bold("📡 CooperCorp Signal Accuracy Report"))
    print(bold("=" * 45))
    if args.days:
        print(f"  Period: Last {args.days} days")
    if args.ticker:
        print(f"  Ticker: {args.ticker.upper()}")
    if args.scan_time:
        print(f"  Scan window: {args.scan_time}")
    print()
    print(f"  Total signals logged:  {bold(str(total))}")
    print(f"  Verified:              {bold(str(verified))} ({pct_verified:.0f}%)")
    print()

    # Per-action rows
    buy_count = action_counts.get("BUY", 0)
    sell_count = action_counts.get("SELL", 0)
    hold_count = action_counts.get("HOLD", 0)
    pass_count = action_counts.get("PASS", 0)

    buy_acc = stats.get("buy_accuracy", 0)
    sell_acc = stats.get("sell_accuracy", 0)
    hold_acc = stats.get("hold_accuracy", 0)
    pass_qual = stats.get("pass_quality", 0)

    buy_avg = avg_accuracy_pct("BUY")
    sell_avg = avg_accuracy_pct("SELL")
    hold_avg = avg_accuracy_pct("HOLD")
    pass_avg = avg_accuracy_pct("PASS")

    def avg_str(val, prefix="+"):
        if val is None:
            return ""
        sign = "+" if val >= 0 else ""
        return f" | Avg when right: {sign}{val:.1f}%"

    print(f"  📈 BUY  signals: {buy_count:5d} | Accuracy: {accuracy_color(buy_acc)}{avg_str(buy_avg)}")
    print(f"  📉 SELL signals: {sell_count:5d} | Accuracy: {accuracy_color(sell_acc)}{avg_str(sell_avg)}")
    print(f"  ⏸️  HOLD signals: {hold_count:5d} | Accuracy: {accuracy_color(hold_acc)}{avg_str(hold_avg)}")
    print(f"  🚫 PASS signals: {pass_count:5d} | Quality:  {accuracy_color(pass_qual)}{avg_str(pass_avg)}")
    print()

    # Best/worst scan times
    by_st = stats.get("by_scan_time", {})
    best_st = stats.get("best_scan_time")
    worst_st = stats.get("worst_scan_time")

    if best_st and best_st in by_st:
        acc = by_st[best_st]["accuracy"]
        cnt = by_st[best_st]["count"]
        print(f"  🕐 Best scan time:  {cyan(best_st)} ({accuracy_color(acc)} accuracy, {cnt} signals)")

    if worst_st and worst_st in by_st and worst_st != best_st:
        acc = by_st[worst_st]["accuracy"]
        cnt = by_st[worst_st]["count"]
        print(f"  🕐 Worst scan time: {cyan(worst_st)} ({accuracy_color(acc)} accuracy, {cnt} signals)")

    # Best/worst tickers
    by_tk = stats.get("by_ticker", {})
    best_tk = stats.get("best_ticker")
    worst_tk = stats.get("worst_ticker")

    if best_tk and best_tk in by_tk:
        acc = by_tk[best_tk]["accuracy"]
        cnt = by_tk[best_tk]["count"]
        print(f"  📊 Best ticker:  {cyan(best_tk)} ({accuracy_color(acc)} accuracy, {cnt} signals)")

    if worst_tk and worst_tk in by_tk and worst_tk != best_tk:
        acc = by_tk[worst_tk]["accuracy"]
        cnt = by_tk[worst_tk]["count"]
        print(f"  📊 Worst ticker: {cyan(worst_tk)} ({accuracy_color(acc)} accuracy, {cnt} signals)")

    # All scan times (sorted)
    if by_st and len(by_st) > 1:
        print()
        print(bold("  📅 Scan Time Breakdown:"))
        for st in sorted(by_st.keys()):
            data = by_st[st]
            print(f"     {st:8s}: {accuracy_color(data['accuracy'])} ({data['count']} signals)")

    # Top tickers (top 5 by count)
    if by_tk and len(by_tk) > 1:
        print()
        print(bold("  📈 Top Tickers by Signal Count:"))
        top_tickers = sorted(by_tk.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
        for tk, data in top_tickers:
            print(f"     {tk:6s}: {accuracy_color(data['accuracy'])} ({data['count']} signals)")

    # Insights
    insights = build_insights(stats, signals)
    if insights:
        print()
        print(bold("  🧠 Actionable Insights:"))
        for insight in insights:
            print(f"     - {insight}")

    print()


def main():
    parser = argparse.ArgumentParser(description="CooperCorp Signal Accuracy Report")
    parser.add_argument("--days", type=int, default=None, help="Filter to last N days")
    parser.add_argument("--ticker", type=str, default=None, help="Filter to specific ticker")
    parser.add_argument("--scan-time", dest="scan_time", type=str, default=None,
                        help="Filter to specific scan time (e.g. 9:30)")
    args = parser.parse_args()

    sl = SignalLogger()
    stats = sl.get_accuracy_stats(
        days=args.days,
        ticker=args.ticker,
        scan_time=args.scan_time,
    )
    signals = sl.get_signals(
        days=args.days,
        ticker=args.ticker,
        scan_time=args.scan_time,
    )
    print_report(stats, signals, args)


if __name__ == "__main__":
    main()
