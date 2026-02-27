"""
CooperCorp PRJ-002 — Trade Executor
Parses BUY/SELL/HOLD from agent final_trade_decision and routes to AlpacaBroker.

Resilience features integrated:
- Gap 1: Bracket orders (hard stops at Alpaca)
- Gap 2: Daily circuit breaker
- Gap 4: Earnings risk filter (-2.0 score penalty)
- Gap 6: Short selling support
- Gap 7: Swing trade tagging
- Gap 9: Trade lock (race condition prevention)
- Gap 10: Market hours check
"""
import re
import uuid
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tradingagents.brokers.alpaca import AlpacaBroker
from tradingagents.risk.circuit_breaker import CircuitBreaker
from tradingagents.risk.trade_lock import TradeLock
from tradingagents.risk.trade_tags import TradeTagger
from tradingagents.filters.earnings_filter import EarningsFilter
from tradingagents.utils.market_hours import is_market_open
from tradingagents.learning.post_mortem import PostMortem
from tradingagents.learning.pattern_tracker import PatternTracker
from tradingagents.signals.signal_logger import SignalLogger

logger = logging.getLogger(__name__)
LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "executions.jsonl"
OPEN_TRADES_DIR = Path(__file__).parent.parent.parent / "logs" / "open_trades"


class TradeExecutor:
    def __init__(self, broker: Optional[AlpacaBroker] = None, portfolio_pct: float = 0.05):
        self.broker = broker or AlpacaBroker()
        self.portfolio_pct = portfolio_pct
        self.circuit_breaker = CircuitBreaker(self.broker)
        self.trade_tagger = TradeTagger()
        self.earnings_filter = EarningsFilter()
        self.post_mortem = PostMortem()
        self.pattern_tracker = PatternTracker()
        self.signal_logger = SignalLogger()
        OPEN_TRADES_DIR.mkdir(parents=True, exist_ok=True)

    def parse_decision(self, text: str, symbol: str) -> dict:
        """Extract BUY/SELL/HOLD action from agent output text."""
        match = re.search(r'\b(BUY|SELL|HOLD)\b', text.upper())
        action = match.group(1) if match else "HOLD"

        # Detect swing trade intent
        is_swing = bool(re.search(r'\bswing\b', text, re.IGNORECASE))

        return {
            "action": action,
            "symbol": symbol.upper(),
            "reasoning": text[:500],
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "is_swing": is_swing,
        }

    def calculate_qty(self, symbol: str) -> float:
        """Size position as portfolio_pct of buying power / current price."""
        buying_power = self.broker.get_buying_power()
        budget = buying_power * self.portfolio_pct
        bar = self.broker.get_latest_bar(symbol)
        if bar is None:
            raise ValueError(f"No price data for {symbol}")
        price = float(bar["close"])
        qty = max(1, int(budget / price))
        logger.info(f"Sizing: budget=${budget:.2f}, price=${price:.2f}, qty={qty}")
        return qty

    def is_long_position(self, symbol: str) -> bool:
        """Returns True if we currently hold a long position in symbol."""
        pos = self.broker.get_position(symbol)
        if pos is None:
            return False
        return float(pos.qty) > 0

    def _apply_earnings_penalty(self, symbol: str, score: float = 0.0) -> float:
        """Subtract earnings penalty from score if earnings are imminent."""
        penalty = self.earnings_filter.score_penalty(symbol, days_ahead=1)
        return score + penalty

    def _build_signal_record(self, decision: dict, acted_on: bool, skip_reason: str = None,
                              scan_time: str = None) -> dict:
        """Build a signal record for logging. Extracts known fields from decision."""
        now = datetime.now(timezone.utc)
        return {
            "id": str(uuid.uuid4()),
            "timestamp": now.isoformat(),
            "scan_time": scan_time or decision.get("scan_time", now.strftime("%-H:%M")),
            "ticker": decision.get("symbol", "UNKNOWN"),
            "action": decision.get("action", "UNKNOWN"),
            "score": decision.get("score", 0.0),
            "conviction": decision.get("conviction", 0),
            "price_at_signal": decision.get("price_at_signal", 0.0),
            "stop_loss": decision.get("stop_loss"),
            "target": decision.get("target"),
            "acted_on": acted_on,
            "skip_reason": skip_reason,
            "analysis_summary": decision.get("reasoning", "")[:200],
            "verified": False,
            "price_1h_later": None,
            "price_4h_later": None,
            "price_eod": None,
            "target_hit": None,
            "stop_hit": None,
            "signal_correct": None,
            "accuracy_pct": None,
        }

    def execute(self, decision: dict, dry_run: bool = False) -> Optional[dict]:
        """Execute the trade decision with full resilience checks."""
        action = decision["action"]
        symbol = decision["symbol"]
        is_swing = decision.get("is_swing", False)

        # Gap 10: Market hours check
        if not is_market_open() and not dry_run:
            logger.info(f"Market is closed — skipping {action} on {symbol}")
            self._log(decision, order=None, dry_run=dry_run, skip_reason="market_closed")
            self.signal_logger.log_signal(
                self._build_signal_record(decision, acted_on=False, skip_reason="market_closed")
            )
            return None

        if action == "HOLD":
            logger.info(f"HOLD on {symbol} — no order placed")
            self._log(decision, order=None, dry_run=dry_run)
            self.signal_logger.log_signal(
                self._build_signal_record(decision, acted_on=False, skip_reason="hold_decision")
            )
            return None

        # Gap 2: Circuit breaker check
        cb_status = self.circuit_breaker.check()
        if not cb_status["ok"]:
            logger.warning(f"Circuit breaker tripped — skipping {action} on {symbol}: {cb_status['reason']}")
            self._log(decision, order=None, dry_run=dry_run, skip_reason=f"circuit_breaker: {cb_status['reason']}")
            self.signal_logger.log_signal(
                self._build_signal_record(
                    decision, acted_on=False,
                    skip_reason=f"circuit_breaker: {cb_status['reason']}"
                )
            )
            return None

        # Gap 4: Earnings penalty (log it; if score-based system: adjust score)
        earnings_penalty = self.earnings_filter.score_penalty(symbol, days_ahead=1)
        if earnings_penalty < 0:
            logger.warning(f"Earnings imminent for {symbol} — score penalty {earnings_penalty} applied")
            # If high penalty and this isn't already a strong conviction, hold
            # (For now: log only; scoring matrix integration point)

        qty = self.calculate_qty(symbol)

        # Gap 6: Short selling logic
        if action == "SELL":
            if self.is_long_position(symbol):
                logger.info(f"SELL on {symbol} — closing existing long position")
                side = "sell"  # Close long, don't open short
            else:
                logger.info(f"SELL on {symbol} — opening short position")
                side = "sell"  # Short sell

        elif action == "BUY":
            side = "buy"
        else:
            side = "buy"

        # Gap 7: Tag swing trades
        if is_swing:
            self.trade_tagger.tag(symbol, "swing")
            logger.info(f"Tagged {symbol} as swing trade")

        if dry_run:
            result = {"dry_run": True, "symbol": symbol, "side": side, "qty": qty, "order_class": "bracket"}
            logger.info(f"DRY RUN: would {side} {qty} {symbol} (bracket)")
            self._log(decision, order=result, dry_run=True)
            self.signal_logger.log_signal(
                self._build_signal_record(decision, acted_on=False, skip_reason="dry_run")
            )
            return result

        # Gap 9: Trade lock to prevent race conditions
        lock = TradeLock()
        acquired = lock.acquire(timeout=10)
        if not acquired:
            logger.error(f"TradeLock: could not acquire lock — skipping {action} on {symbol}")
            self._log(decision, order=None, dry_run=dry_run, skip_reason="trade_lock_timeout")
            self.signal_logger.log_signal(
                self._build_signal_record(decision, acted_on=False, skip_reason="trade_lock_timeout")
            )
            return None

        try:
            # Gap 1: Use bracket orders instead of simple market orders
            order = self.broker.submit_bracket_order(symbol, qty, side)
            result = {
                "order_id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "qty": order.qty,
                "status": order.status,
                "order_class": "bracket",
                "submitted_at": str(order.submitted_at),
                "earnings_penalty": earnings_penalty,
                "is_swing": is_swing,
            }
            logger.info(f"BRACKET ORDER PLACED: {result}")
            self._log(decision, order=result, dry_run=False)
            self.signal_logger.log_signal(
                self._build_signal_record(decision, acted_on=True)
            )
            return result
        finally:
            lock.release()

    def save_open_trade(self, symbol: str, side: str, entry_price: float, qty: float, analysis_text: str = ""):
        """Persist open trade details + entry analysis for post-mortem use."""
        trade_file = OPEN_TRADES_DIR / f"{symbol.upper()}.json"
        data = {
            "symbol": symbol.upper(),
            "side": side,
            "entry_price": entry_price,
            "qty": qty,
            "analysis_at_entry": analysis_text,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).date().isoformat(),
        }
        with open(trade_file, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Open trade saved: {symbol}")

    def on_trade_close(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str = "unknown",
        hold_minutes: int = 0,
    ):
        """
        Called when a position closes. Triggers post-mortem for losses
        and reinforcement logging for wins.
        """
        trade_file = OPEN_TRADES_DIR / f"{symbol.upper()}.json"
        if not trade_file.exists():
            logger.warning(f"on_trade_close: no open trade file for {symbol}")
            return

        with open(trade_file) as f:
            open_trade = json.load(f)

        side = open_trade.get("side", "buy")
        entry_price = open_trade.get("entry_price", 0)
        qty = open_trade.get("qty", 0)
        analysis_at_entry = open_trade.get("analysis_at_entry", "")
        date = open_trade.get("date", datetime.now(timezone.utc).date().isoformat())

        if side == "buy":
            pnl_pct = (exit_price - entry_price) / entry_price if entry_price else 0
        else:
            pnl_pct = (entry_price - exit_price) / entry_price if entry_price else 0

        trade = {
            "ticker": symbol.upper(),
            "side": side,
            "entry": entry_price,
            "exit": exit_price,
            "pnl_pct": round(pnl_pct, 4),
            "hold_minutes": hold_minutes,
            "exit_reason": exit_reason,
            "analysis_at_entry": analysis_at_entry,
            "date": date,
        }

        if pnl_pct < 0:
            # Loss — full post-mortem
            logger.info(f"Loss on {symbol} ({pnl_pct:+.1%}): running post-mortem")
            try:
                lesson = self.post_mortem.analyze(trade)
                self.post_mortem.save_lesson(lesson)
                pattern = lesson.get("pattern")
                if pattern and pattern != "unknown":
                    self.pattern_tracker.record_pattern(pattern, trade)
                logger.info(f"Post-mortem complete: {lesson['lesson']}")
            except Exception as e:
                logger.error(f"Post-mortem failed for {symbol}: {e}")
        else:
            # Win — log for reinforcement
            logger.info(f"Win on {symbol} ({pnl_pct:+.1%}): recording reinforcement")
            reinforcement_path = OPEN_TRADES_DIR.parent / "reinforcements.jsonl"
            with open(reinforcement_path, "a") as f:
                f.write(json.dumps({
                    "ticker": symbol.upper(),
                    "pnl_pct": round(pnl_pct, 4),
                    "exit_reason": exit_reason,
                    "date": date,
                    "analysis_snippet": analysis_at_entry[:300],
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }) + "\n")

        # Clean up open trade file
        trade_file.unlink(missing_ok=True)

    def _log(self, decision: dict, order: Optional[dict], dry_run: bool, skip_reason: str = None):
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "order": order,
            "dry_run": dry_run,
            "skip_reason": skip_reason,
        }
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
