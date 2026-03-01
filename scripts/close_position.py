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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
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

    # Detect if this is an options contract (OCC symbol contains letters+digits+C/P+8digits)
    import re
    is_options = bool(re.match(r'^[A-Z]{1,6}\d{6}[CP]\d{8}$', args.ticker))
    if is_options:
        print(f"Options contract detected: {args.ticker}")
        # Options use sell_to_close instead of submit_order
        if not args.dry_run:
            try:
                order = broker.sell_to_close(args.ticker, int(abs(qty)))
                print(f"Sell to close: {order.symbol} {order.qty} @ market | status: {order.status}")
            except Exception as e:
                print(f"sell_to_close failed: {e}")
        pnl_per_contract = pnl_dollar / abs(qty) if qty != 0 else 0
        print(f"Options P&L: {pnl_pct:.1f}% | ${pnl_dollar:.2f} ({abs(qty):.0f} contracts × ${pnl_per_contract:.2f})")
        return  # Options don't need the learning system (no same reflection)

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

    # Log outcome to signal DB
    try:
        from pathlib import Path as _Path
        from tradingagents.db.signal_db import log_outcome as db_log_outcome
        _sid_file = _Path(__file__).parent.parent / "logs" / "open_trades" / f"{args.ticker}.signal_id"
        if _sid_file.exists():
            _signal_id = int(_sid_file.read_text().strip())
            db_log_outcome(_signal_id, exit_price, pnl_pct / 100.0, args.reason)
            _sid_file.unlink(missing_ok=True)
            print(f"Signal DB outcome logged: signal_id={_signal_id} pnl={pnl_pct:.1f}%")
    except Exception as _e:
        print(f"WARN: signal_db outcome log failed: {_e}")

    # Post exit card to Discord (standardized signal card format)
    try:
        import subprocess
        from tradingagents.discord_signal_card import format_exit_card
        hold_str = f"{hold_minutes // 60}h {hold_minutes % 60}m" if hold_minutes > 60 else f"{hold_minutes}m"
        direction = "LONG" if qty > 0 else "SHORT"

        # Get lesson if post-mortem has one
        lesson = None
        try:
            pm_file = Path(__file__).parent.parent / "logs" / "LESSONS.md"
            if pm_file.exists():
                recent = pm_file.read_text().split("\n")
                for line in reversed(recent[-20:]):
                    if "→" in line or "Lesson:" in line:
                        lesson = line.strip().lstrip("- ").strip()
                        break
        except Exception:
            pass

        exit_card = format_exit_card(
            symbol=args.ticker,
            name=args.ticker,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            pl_pct=pnl_pct,
            pl_dollar=pnl_dollar,
            reason=args.reason,
            held_time=hold_str,
            lesson=lesson if pnl_pct < 0 else None,
            agent="Executor ⚡",
        )

        # #paper-trades always
        subprocess.run(["openclaw", "message", "send", "--channel", "discord",
            "--target", "1468597633756037385", "--message", exit_card], capture_output=True)

        # Route winners / losers
        if pnl_pct >= 0:
            subprocess.run(["openclaw", "message", "send", "--channel", "discord",
                "--target", "1468620383019077744", "--message", exit_card], capture_output=True)
        else:
            subprocess.run(["openclaw", "message", "send", "--channel", "discord",
                "--target", "1468620412849229825", "--message", exit_card], capture_output=True)

        # #gamespoofer-trades (private)
        subprocess.run(["openclaw", "message", "send", "--channel", "discord",
            "--target", "1469519503174926568", "--message", exit_card], capture_output=True)

        print(f"Exit card posted to Discord")
    except Exception as e:
        print(f"Warning: Discord exit card failed: {e}")

    # Clear trailing stop HWM for closed position
    try:
        from tradingagents.risk.trailing_stop import TrailingStopManager
        TrailingStopManager().clear(args.ticker)
        print(f"Trailing stop HWM cleared for {args.ticker}")
    except Exception as e:
        print(f"Warning: trailing stop clear failed: {e}")

    # ── BM25 Memory + LLM Reflection (Gap 1 & 2 closure) ───────────────────
    try:
        import subprocess as _sp
        _direction = "long" if qty > 0 else "short"
        _score_file = REPO / "logs" / "open_trades" / f"{args.ticker}.score"
        _score = float(_score_file.read_text().strip()) if _score_file.exists() else 0.0
        _conviction_file = REPO / "logs" / "open_trades" / f"{args.ticker}.conviction"
        _conviction = int(_conviction_file.read_text().strip()) if _conviction_file.exists() else 0

        _ctx_parts = []
        try:
            import yfinance as yf
            _vix = yf.Ticker("^VIX").fast_info.last_price
            _ctx_parts.append(f"VIX={_vix:.1f}")
            _btc = yf.Ticker("BTC-USD").fast_info.last_price
            _ctx_parts.append(f"BTC={_btc:,.0f}")
        except Exception:
            pass
        _market_context = ", ".join(_ctx_parts) if _ctx_parts else "context unavailable"

        _reflect_cmd = [
            "python3", str(REPO / "scripts" / "reflect_on_trade.py"),
            "--ticker", args.ticker,
            "--entry", str(entry_price),
            "--exit", str(exit_price),
            "--pnl-pct", str(round(pnl_pct, 2)),
            "--direction", _direction,
            "--exit-reason", args.reason.lower(),
            "--score", str(_score),
            "--conviction", str(_conviction),
            "--market-context", _market_context,
        ]
        _sp.Popen(_reflect_cmd, cwd=str(REPO))
        print(f"Reflection spawned for {args.ticker} (async)")

        # Update rolling Kelly fraction from signal DB (async, non-blocking)
        try:
            _calibrate_cmd = ["python3", str(REPO / "tradingagents" / "graph" / "position_calibrator.py")]
            _sp.Popen(_calibrate_cmd, cwd=str(REPO))
            print("Kelly calibration spawned (async)")
        except Exception as _ce:
            print(f"WARN: Kelly calibration spawn failed (non-fatal): {_ce}")

        for _suf in [".score", ".conviction"]:
            _f = REPO / "logs" / "open_trades" / f"{args.ticker}{_suf}"
            if _f.exists():
                _f.unlink()
    except Exception as e:
        print(f"WARN: Reflection spawn failed (non-fatal): {e}")


if __name__ == "__main__":
    main()
