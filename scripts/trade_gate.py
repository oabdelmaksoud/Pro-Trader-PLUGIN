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
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

from tradingagents.brokers.alpaca import AlpacaBroker
from tradingagents.risk.circuit_breaker import CircuitBreaker
from tradingagents.filters.earnings_filter import EarningsFilter
from tradingagents.filters.correlation_filter import CorrelationFilter
from tradingagents.signals.signal_logger import SignalLogger
from tradingagents.risk.trade_lock import TradeLock
from tradingagents.utils.market_hours import is_market_open
from tradingagents.utils.strategy_config import get_position_pct, get_vix_multiplier, get_current_vix

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

    # Guru bonus injection (from guru_tracker.py signals)
    guru_bonus = 0.0
    try:
        guru_signals_path = REPO / "logs" / "guru_signals.json"
        if guru_signals_path.exists():
            guru_signals = json.loads(guru_signals_path.read_text())
            if args.ticker in guru_signals:
                guru_bonus = float(guru_signals[args.ticker].get("guru_bonus", 0))
                reasons = guru_signals[args.ticker].get("reasons", [])
                if guru_bonus > 0:
                    print(f"GURU BONUS: +{guru_bonus} for {args.ticker} — {reasons[-1] if reasons else 'guru signal'}")
                    args.score = min(10.0, args.score + guru_bonus)
                    signal["score"] = args.score
                    signal["analysis_summary"] += f" | Guru bonus +{guru_bonus}"
    except Exception as e:
        print(f"WARN: Could not load guru signals: {e}")

    # Drawdown circuit breaker check
    try:
        drawdown_path = REPO / "logs" / "drawdown_state.json"
        if drawdown_path.exists():
            dd = json.loads(drawdown_path.read_text())
            if dd.get("halted"):
                signal["skip_reason"] = f"Portfolio drawdown circuit breaker active (down {dd.get('drawdown_pct','?')}%)"
                logger.log_signal(signal)
                print(f"SKIP: Drawdown circuit breaker halted new entries")
                return
    except Exception as e:
        print(f"WARN: Could not check drawdown state: {e}")

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

    # Gate 4b: Portfolio heat check
    from tradingagents.risk.portfolio_heat import PortfolioHeat
    heat = PortfolioHeat(broker)
    position_size_pct = float(strategy.get("position", {}).get("default_pct", 0.05)) * 100
    heat_ok, heat_reason = heat.can_add_position(args.ticker, position_size_pct)
    if not heat_ok and args.action == "BUY":
        signal["skip_reason"] = f"Portfolio heat: {heat_reason}"
        logger.log_signal(signal)
        print(f"SKIP: {heat_reason}")
        return

    # Gate 4c: Correlation filter
    corr = CorrelationFilter(broker)
    corr_check = corr.is_too_correlated(args.ticker)
    if not corr_check["ok"] and args.action == "BUY":
        signal["skip_reason"] = corr_check["reason"]
        logger.log_signal(signal)
        print(f"SKIP: {corr_check['reason']}")
        return

    # Gate 4c: Already own this ticker? Don't double-buy
    already_owned = any(p.symbol == args.ticker for p in positions)
    if args.action == "BUY" and already_owned:
        signal["skip_reason"] = f"Already hold {args.ticker}"
        logger.log_signal(signal)
        print(f"SKIP: Already own {args.ticker}")
        return

    # Gate 5: Trade lock
    lock = TradeLock()
    if not lock.acquire():
        signal["skip_reason"] = "Trade lock active — concurrent execution"
        logger.log_signal(signal)
        print(f"SKIP: Trade lock active")
        return

    try:
        # Size position — Kelly Criterion + VIX-adjusted, conviction-scaled
        bp = broker.get_buying_power()
        vix = get_current_vix()
        side = "buy" if args.action == "BUY" else "sell"
        try:
            from tradingagents.risk.kelly_sizing import get_kelly_size
            kelly_result = get_kelly_size(
                ticker=args.ticker,
                portfolio_value=bp,
                vix=vix,
                current_price=signal["price_at_signal"]
            )
            budget = kelly_result["dollar_amount"]
            qty = kelly_result["shares"] or max(1, int(budget / signal["price_at_signal"]))
            print(f"Sizing (Kelly): fraction={kelly_result['fraction']:.1%} × VIX({vix:.0f}) = ${budget:.0f} = {qty} shares [WR={kelly_result['win_rate_used']:.0%}, method={kelly_result['method']}]")
        except Exception as _ke:
            print(f"WARN: Kelly sizing failed ({_ke}), falling back to conviction-based")
            vix_mult = get_vix_multiplier(vix)
            conviction_pct = get_position_pct(args.conviction)
            final_pct = conviction_pct * vix_mult
            budget = bp * final_pct
            qty = max(1, int(budget / signal["price_at_signal"])) if signal["price_at_signal"] > 0 else 0
            print(f"Sizing (fallback): conviction={args.conviction} → {conviction_pct*100:.0f}% × VIX({vix:.0f}) mult {vix_mult} = {final_pct*100:.1f}% = {qty} shares")

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

        # Notify members with ticker in their personal watchlist
        try:
            member_prefs_path = REPO / "logs" / "member_prefs.json"
            if member_prefs_path.exists():
                member_prefs = json.loads(member_prefs_path.read_text())
                for uid, pdata in member_prefs.items():
                    watchlist = pdata.get("watchlist", [])
                    ch_id = pdata.get("channel_id", "")
                    if args.ticker in watchlist and ch_id:
                        risk = pdata.get("risk", "moderate")
                        personal_msg = (
                            f"🔔 SIGNAL ON YOUR WATCHLIST — {args.ticker}\n"
                            f"📊 Score: {args.score}/10 | Conviction: {args.conviction}/10\n"
                            f"💰 Entry: ~${signal['price_at_signal']:.2f} | Stop: ${signal['stop_loss']:.2f} (-3%) | Target: ${signal['target']:.2f} (+8%)\n"
                            f"⚙️ Risk profile: {risk}\n"
                            f"— Cooper 🦅 | Personal Alert"
                        )
                        import subprocess as _sub
                        _sub.run(
                            ["openclaw", "message", "send", "--channel", "discord",
                             "--target", ch_id, "--message", personal_msg],
                            capture_output=True, timeout=10
                        )
                        print(f"Personal alert sent to {pdata.get('username', uid)}")
        except Exception as e:
            print(f"WARN: Personal alert failed (non-fatal): {e}")

        # Log to signal DB
        try:
            from tradingagents.db.signal_db import log_signal as db_log_signal, mark_entered
            db_signal_id = db_log_signal(
                ticker=args.ticker,
                pre_score=args.score,
                final_score=args.score,
                conviction=args.conviction
            )
            mark_entered(db_signal_id, signal["price_at_signal"])
            # Persist signal_id for close_position.py to use
            import json as _json
            _sid_path = Path(__file__).parent.parent / "logs" / "open_trades"
            _sid_path.mkdir(parents=True, exist_ok=True)
            (_sid_path / f"{args.ticker}.signal_id").write_text(str(db_signal_id))
            # Write score/conviction for reflection engine
            (_sid_path / f"{args.ticker}.score").write_text(str(final_score))
            (_sid_path / f"{args.ticker}.conviction").write_text(str(args.conviction))
        except Exception as _e:
            print(f"WARN: signal_db log error: {_e}")

        # VWAP advisory check
        try:
            from tradingagents.execution.vwap_entry import should_enter_now, get_limit_price
            vwap_ok, vwap_reason, suggested_limit = should_enter_now(args.ticker, signal["price_at_signal"], args.score)
            signal["vwap_checked"] = True
            signal["limit_price"] = suggested_limit
            if not vwap_ok:
                print(f"VWAP advisory: {vwap_reason} (suggested limit: ${suggested_limit:.2f})")
        except Exception:
            pass

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

        # Post signal card (standardized format) to #paper-trades + #gamespoofer-trades
        import subprocess
        try:
            from tradingagents.discord_signal_card import format_signal_card
            price = signal["price_at_signal"]
            t1 = signal["target"]
            t2 = round(price + (t1 - price) * 1.5, 2)  # Extended T2
            direction = "LONG" if args.action == "BUY" else "SHORT"
            card = format_signal_card(
                symbol=args.ticker,
                name=args.ticker,
                direction=direction,
                current_price=price,
                change_24h=0.0,  # Live change fetched inside
                entry=price,
                stop=signal["stop_loss"],
                t1=t1,
                t2=t2,
                score=float(args.score),
                conviction=int(args.conviction),
                catalyst=args.analysis[:80] if args.analysis else None,
                agent="Cooper 🦅",
            )
        except Exception as e:
            # Fallback if chart fails
            card = (
                f"📊 {args.ticker} {args.action} @ ${signal['price_at_signal']:.2f} | "
                f"Score {args.score}/10 | Conv {args.conviction}/10\n"
                f"Stop ${signal['stop_loss']:.2f} | Target ${signal['target']:.2f} | "
                f"Size {qty} shares (${budget:.0f})"
            )

        # Post to #paper-trades
        subprocess.run([
            "openclaw", "message", "send",
            "--channel", "discord",
            "--target", "1468597633756037385",
            "--message", card,
        ], capture_output=True)

        # Post to #gamespoofer-trades (private)
        subprocess.run([
            "openclaw", "message", "send",
            "--channel", "discord",
            "--target", "1469519503174926568",
            "--message", card,
        ], capture_output=True)

    except Exception as e:
        print(f"ERROR executing order: {e}")
        signal["skip_reason"] = f"Error: {e}"
        logger.log_signal(signal)
    finally:
        lock.release()

if __name__ == "__main__":
    main()
