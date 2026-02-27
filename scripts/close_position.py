#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Position Closer
Closes a position, calls on_trade_close() for post-mortem + ledger, posts to Discord.

Usage:
  python3 scripts/close_position.py --ticker NVDA --reason TARGET_HIT
  python3 scripts/close_position.py --ticker NVDA --exit-price 198.50 --reason STOP_HIT
  python3 scripts/close_position.py --ticker NVDA --reason MANUAL --dry-run
"""
import argparse, sys, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from tradingagents.brokers.alpaca import AlpacaBroker
from tradingagents.execution.executor import TradeExecutor
from tradingagents.performance.ledger import TradeLedger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--exit-price", type=float, default=None)
    parser.add_argument("--reason", default="MANUAL",
                        choices=["TARGET_HIT", "STOP_HIT", "EOD_CLOSE", "THESIS_BROKEN", "MANUAL"])
    parser.add_argument("--hold-minutes", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    broker = AlpacaBroker()
    executor = TradeExecutor(broker=broker)
    ledger = TradeLedger()

    # Get current position
    pos = broker.get_position(args.ticker)
    if pos is None:
        print(f"No open position for {args.ticker}")
        return

    qty = float(pos.qty)
    entry_price = float(pos.avg_entry_price)
    current_price = float(pos.current_price)
    pnl_pct = float(pos.unrealized_plpc) * 100
    pnl_dollar = float(pos.unrealized_pl)
    exit_price = args.exit_price or current_price
    side = "sell" if qty > 0 else "buy"

    print(f"Position: {args.ticker} qty={qty} entry=${entry_price:.2f} current=${current_price:.2f} P&L={pnl_pct:.1f}% (${pnl_dollar:.2f})")

    if not args.dry_run:
        # Submit close order
        order = broker.submit_order(args.ticker, abs(qty), side)
        print(f"Closed: {order.symbol} {order.side} {order.qty} status={order.status}")

    # Calculate hold time from open_trades file if available
    open_trade_file = Path(__file__).parent.parent / "logs" / "open_trades" / f"{args.ticker.upper()}.json"
    hold_minutes = args.hold_minutes
    if open_trade_file.exists():
        try:
            data = json.loads(open_trade_file.read_text())
            opened_at = datetime.fromisoformat(data["opened_at"])
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            hold_minutes = int((datetime.now(timezone.utc) - opened_at).total_seconds() / 60)
        except Exception as e:
            print(f"Warning: could not read open_trades file: {e}")

    # Wire learning system
    try:
        executor.on_trade_close(
            symbol=args.ticker,
            exit_price=exit_price,
            exit_reason=args.reason,
            hold_minutes=hold_minutes,
        )
        print(f"on_trade_close() called — post-mortem triggered")
    except Exception as e:
        print(f"Warning: on_trade_close failed: {e}")

    # Write to ledger (using dict-style call for compatibility)
    try:
        ledger.record_close(
            ticker=args.ticker,
            side="long" if qty > 0 else "short",
            entry_price=entry_price,
            exit_price=exit_price,
            qty=abs(qty),
            hold_minutes=hold_minutes,
            reason=args.reason,
        )
        print(f"Ledger updated. P&L: {pnl_pct:.1f}% (${pnl_dollar:.2f})")
    except Exception as e:
        print(f"Warning: ledger.record_close failed: {e}")

    # Clear trailing stop HWM for closed position
    try:
        from tradingagents.risk.trailing_stop import TrailingStopManager
        TrailingStopManager().clear(args.ticker)
        print(f"Trailing stop HWM cleared for {args.ticker}")
    except Exception as e:
        print(f"Warning: trailing stop clear failed: {e}")


if __name__ == "__main__":
    main()
