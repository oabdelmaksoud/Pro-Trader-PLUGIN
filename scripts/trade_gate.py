#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Trade Gate
Single entry point for all cron-triggered trade execution.
Enforces: circuit breaker → earnings filter → bracket order → signal logging

Usage:
  python3 scripts/trade_gate.py --ticker NVDA --action BUY --score 7.8 --conviction 8 --analysis "Strong breakout" --scan-time "9:30"
  python3 scripts/trade_gate.py --ticker NVDA --action PASS --score 6.2 --conviction 5 --analysis "Below threshold" --scan-time "9:30"
"""
import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from tradingagents.brokers.alpaca import AlpacaBroker
from tradingagents.risk.circuit_breaker import CircuitBreaker
from tradingagents.filters.earnings_filter import EarningsFilter
from tradingagents.signals.signal_logger import SignalLogger
from tradingagents.risk.trade_lock import TradeLock
from tradingagents.utils.market_hours import is_market_open

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--action", required=True, choices=["BUY", "SELL", "PASS", "HOLD"])
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--conviction", type=int, required=True)
    parser.add_argument("--analysis", default="", help="1-2 sentence summary")
    parser.add_argument("--scan-time", default="unknown")
    parser.add_argument("--portfolio-pct", type=float, default=0.05)
    parser.add_argument("--stop-pct", type=float, default=0.03)
    parser.add_argument("--target-pct", type=float, default=0.08)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    broker = AlpacaBroker()
    logger = SignalLogger()

    signal = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scan_time": args.scan_time,
        "ticker": args.ticker,
        "action": args.action,
        "score": args.score,
        "conviction": args.conviction,
        "price_at_signal": 0.0,
        "stop_loss": 0.0,
        "target": 0.0,
        "acted_on": False,
        "skip_reason": None,
        "analysis_summary": args.analysis,
        "verified": False,
        "price_1h_later": None,
        "price_4h_later": None,
        "price_eod": None,
        "target_hit": None,
        "stop_hit": None,
        "signal_correct": None,
        "accuracy_pct": None,
    }

    # Always get price data, even for PASSes (for accuracy tracking)
    try:
        bar = broker.get_latest_bar(args.ticker)
        price = float(bar["close"])
        signal["price_at_signal"] = price
        signal["stop_loss"] = round(price * (1 - args.stop_pct), 2)
        signal["target"] = round(price * (1 + args.target_pct), 2)
    except Exception as e:
        print(f"WARN: Could not get price for {args.ticker}: {e}")

    if args.action in ("PASS", "HOLD"):
        signal["skip_reason"] = f"Score {args.score}/10 below threshold or conviction {args.conviction}/10 below minimum"
        logger.log_signal(signal)
        print(f"SIGNAL LOGGED: {args.action} {args.ticker} score={args.score} conviction={args.conviction}")
        return

    # --- Execution path (BUY or SELL) ---

    # Gate 1: Market hours
    if not is_market_open() and not args.dry_run:
        signal["skip_reason"] = "Market closed"
        logger.log_signal(signal)
        print(f"SKIP: Market closed")
        return

    # Gate 2: Circuit breaker
    cb = CircuitBreaker(broker)
    check = cb.check()
    if not check["ok"]:
        signal["skip_reason"] = f"Circuit breaker: {check['reason']}"
        logger.log_signal(signal)
        print(f"SKIP: {check['reason']}")
        return

    # Gate 3: Earnings proximity (warn but don't block — already penalized in score)
    ef = EarningsFilter()
    if ef.has_earnings_soon(args.ticker, days_ahead=1):
        print(f"WARN: {args.ticker} has earnings within 1 day — high risk")
        signal["analysis_summary"] += " [EARNINGS WARNING]"

    # Gate 4: Position limit
    positions = broker.get_positions()
    has_position = any(p.symbol == args.ticker for p in positions)
    if args.action == "BUY" and len(positions) >= 2 and not has_position:
        signal["skip_reason"] = "Position limit reached (2 max)"
        logger.log_signal(signal)
        print(f"SKIP: At position limit ({len(positions)} positions)")
        return

    # Gate 5: Trade lock
    lock = TradeLock()
    if not lock.acquire():
        signal["skip_reason"] = "Trade lock active — concurrent execution"
        logger.log_signal(signal)
        print(f"SKIP: Trade lock active")
        return

    try:
        # Size position
        bp = broker.get_buying_power()
        budget = bp * args.portfolio_pct
        side = "buy" if args.action == "BUY" else "sell"
        qty = max(1, int(budget / signal["price_at_signal"])) if signal["price_at_signal"] > 0 else 0

        if args.dry_run:
            if signal["price_at_signal"] <= 0:
                print(f"DRY RUN: Would {side} ~N shares of {args.ticker} @ ~$UNKNOWN (market closed, no price data)")
            else:
                print(f"DRY RUN: Would {side} {qty} shares of {args.ticker} @ ~${signal['price_at_signal']:.2f}")
                print(f"  Stop: ${signal['stop_loss']:.2f} | Target: ${signal['target']:.2f}")
            signal["skip_reason"] = "dry_run"
            logger.log_signal(signal)
            return

        if signal["price_at_signal"] <= 0:
            print("ERROR: No price data")
            signal["skip_reason"] = "No price data"
            logger.log_signal(signal)
            return

        # Execute bracket order
        order = broker.submit_bracket_order(
            args.ticker, qty, side,
            stop_loss_pct=args.stop_pct,
            take_profit_pct=args.target_pct
        )

        signal["acted_on"] = True
        signal["skip_reason"] = None
        logger.log_signal(signal)

        # Save open trade record
        import json
        open_trades_dir = Path(__file__).parent.parent / "logs" / "open_trades"
        open_trades_dir.mkdir(parents=True, exist_ok=True)
        (open_trades_dir / f"{args.ticker}.json").write_text(json.dumps({
            "ticker": args.ticker,
            "side": side,
            "qty": qty,
            "entry_price": signal["price_at_signal"],
            "stop_loss": signal["stop_loss"],
            "target": signal["target"],
            "signal_id": signal["id"],
            "analysis_at_entry": args.analysis,
            "opened_at": signal["timestamp"],
            "scan_time": args.scan_time,
        }, indent=2))

        print(f"EXECUTED: {side.upper()} {qty} {args.ticker} @ ~${signal['price_at_signal']:.2f}")
        print(f"  Order ID: {order.id} | Status: {order.status}")
        print(f"  Bracket: Stop ${signal['stop_loss']:.2f} | Target ${signal['target']:.2f}")

    except Exception as e:
        print(f"ERROR executing order: {e}")
        signal["skip_reason"] = f"Error: {e}"
        logger.log_signal(signal)
    finally:
        lock.release()

if __name__ == "__main__":
    main()
