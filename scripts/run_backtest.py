#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Backtest Runner CLI
Usage: python3 scripts/run_backtest.py --tickers NVDA,ARM,MSFT --days 90 --threshold 7.0
"""
import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tradingagents.backtest.engine import BacktestEngine


def main():
    parser = argparse.ArgumentParser(description="CooperCorp Walk-Forward Backtester")
    parser.add_argument("--tickers", default="NVDA,ARM,MSFT,AAPL,META", help="Comma-separated tickers")
    parser.add_argument("--days", type=int, default=90, help="Lookback period in days")
    parser.add_argument("--threshold", type=float, default=7.0, help="Score entry threshold")
    parser.add_argument("--stop-loss", type=float, default=0.03, help="Stop loss fraction (e.g. 0.03=3%)")
    parser.add_argument("--take-profit", type=float, default=0.08, help="Take profit fraction (e.g. 0.08=8%)")
    parser.add_argument("--capital", type=float, default=100_499.0, help="Starting capital")
    parser.add_argument("--output", default=None, help="Output JSON path (default: logs/backtest_latest.json)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    print(f"\n🔬 CooperCorp Backtester")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"Period: {args.days} days | Threshold: {args.threshold} | SL: {args.stop_loss*100:.0f}% | TP: {args.take_profit*100:.0f}%")
    print("-" * 60)

    engine = BacktestEngine(initial_capital=args.capital)
    result = engine.run_backtest(
        tickers=tickers,
        score_threshold=args.threshold,
        lookback_days=args.days,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit
    )
    engine.save_results(result, args.output)

    if "error" in result and result.get("total_trades", 0) == 0:
        print(f"⚠️ {result.get('error', 'No results')}")
        return

    print(f"\n📊 RESULTS")
    print(f"Total Return: {result['total_return_pct']:+.2f}%")
    print(f"Win Rate: {result['win_rate']:.1%} ({result['wins']}W / {result['losses']}L)")
    print(f"Total Trades: {result['total_trades']}")
    print(f"Avg Win: +{result['avg_win_pct']:.2f}% | Avg Loss: {result['avg_loss_pct']:.2f}%")
    print(f"Max Drawdown: -{result['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio: {result['sharpe_ratio']:.2f}")
    print(f"Final Capital: ${result['final_capital']:,.2f}")
    print(f"\nTop Trades:")
    top = sorted(result["trades"], key=lambda t: t["pnl_pct"], reverse=True)[:5]
    for t in top:
        emoji = "🟢" if t["win"] else "🔴"
        print(f"  {emoji} {t['ticker']} {t['entry_date']} → {t['exit_date']}: {t['pnl_pct']:+.2f}% ({t['exit_reason']})")


if __name__ == "__main__":
    main()
