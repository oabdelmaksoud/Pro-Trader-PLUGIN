"""
CooperCorp PRJ-002 — Post-Mortem Engine
Analyzes closed losing trades to extract lessons and tag mistake patterns.
"""
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
LESSONS_FILE = REPO_ROOT / "logs" / "LESSONS.md"
PATTERNS_FILE = REPO_ROOT / "logs" / "patterns.json"


class PostMortem:
    """
    Analyzes closed trades to extract lessons.
    Called automatically when Executor closes a losing position.
    """

    LESSONS_FILE = LESSONS_FILE
    PATTERNS_FILE = PATTERNS_FILE

    # Signals that can fail
    SIGNAL_TYPES = ["catalyst", "technical", "sentiment", "fundamental", "rr"]

    # Known mistake patterns (must match PatternTracker.PATTERNS keys)
    KNOWN_PATTERNS = {
        "chased_breakout": lambda t: t.get("pnl_pct", 0) < -0.02,
        "pre_earnings_entry": lambda t: "earnings" in t.get("exit_reason", "").lower(),
        "low_volume_breakout": lambda t: "volume" in t.get("analysis_at_entry", "").lower()
            and "below" in t.get("analysis_at_entry", "").lower(),
        "macro_ignored": lambda t: "macro" in t.get("analysis_at_entry", "").lower()
            and "bearish" in t.get("analysis_at_entry", "").lower(),
        "poor_rr": lambda t: t.get("pnl_pct", 0) < -0.015 and t.get("hold_minutes", 0) < 30,
        "held_too_long": lambda t: t.get("hold_minutes", 0) > 240 and t.get("pnl_pct", 0) < 0,
        "weak_catalyst": lambda t: "catalyst" in t.get("analysis_at_entry", "").lower()
            and "minor" in t.get("analysis_at_entry", "").lower(),
    }

    def _web_search(self, query: str) -> str:
        """Get relevant news/info using yfinance news for the ticker."""
        try:
            import re
            ticker_match = re.search(r'\b([A-Z]{1,5})\b', query)
            if ticker_match:
                import yfinance as yf
                t = yf.Ticker(ticker_match.group(1))
                news = t.news
                if news:
                    summaries = []
                    for article in news[:5]:
                        title = article.get("title", "")
                        summaries.append(title)
                    return "\n".join(summaries)
            return f"No news found for query: {query}"
        except Exception as e:
            logger.warning(f"Web search failed: {e}")
            return f"Search failed: {e}"

    def analyze(self, trade: dict) -> dict:
        """
        Analyze a closed trade and extract a lesson.

        trade = {
            "ticker": str, "side": str, "entry": float, "exit": float,
            "pnl_pct": float, "hold_minutes": int, "exit_reason": str,
            "analysis_at_entry": str,
            "date": str
        }
        """
        ticker = trade.get("ticker", "UNKNOWN")
        date = trade.get("date", "")
        pnl_pct = trade.get("pnl_pct", 0)
        analysis_at_entry = trade.get("analysis_at_entry", "")
        exit_reason = trade.get("exit_reason", "")

        # Search what actually happened to the stock on that date
        search_query = f"{ticker} stock price drop {date} news reason"
        market_news = self._web_search(search_query)

        # Detect which pattern applies
        pattern = "unknown"
        for pat_name, detector in self.KNOWN_PATTERNS.items():
            try:
                if detector(trade):
                    pattern = pat_name
                    break
            except Exception:
                pass

        # Determine which signal failed based on context
        which_signal_failed = "technical"
        analysis_lower = analysis_at_entry.lower()
        if "catalyst" in analysis_lower and pnl_pct < -0.01:
            which_signal_failed = "catalyst"
        elif "sentiment" in analysis_lower and ("bullish" in analysis_lower or "positive" in analysis_lower):
            which_signal_failed = "sentiment"
        elif "fundamental" in analysis_lower or "pe" in analysis_lower or "earnings" in analysis_lower:
            which_signal_failed = "fundamental"
        elif "risk" in analysis_lower or "r/r" in analysis_lower or "risk/reward" in analysis_lower:
            which_signal_failed = "rr"

        # Build what_went_wrong narrative
        what_went_wrong = (
            f"{ticker} moved {pnl_pct:.1%} against us (exit: {exit_reason}). "
        )
        if market_news:
            what_went_wrong += f"Market context on {date}: {market_news[:300]}"
        else:
            what_went_wrong += f"Entry analysis indicated {analysis_at_entry[:200]}."

        # Suggest scoring adjustment
        adjustment_map = {
            "chased_breakout": {"technical_cap": 2, "description": "Cap technical score at 2 if >3% move without pullback"},
            "pre_earnings_entry": {"earnings_penalty": -2.0, "description": "Enforce -2.0 earnings penalty"},
            "low_volume_breakout": {"volume_required": True, "description": "Require above-avg volume for breakouts"},
            "macro_ignored": {"macro_weight": 1.5, "description": "Increase macro weight by 1.5x"},
            "poor_rr": {"min_rr": 2.0, "description": "Require minimum 2:1 R/R"},
            "held_too_long": {"time_stop_hours": 4, "description": "Apply time stop at 4 hours"},
            "weak_catalyst": {"catalyst_threshold": 3, "description": "Require catalyst score >= 3"},
            "unknown": {},
        }
        adjustment = adjustment_map.get(pattern, {})

        # 1-sentence memorable lesson
        lesson_map = {
            "chased_breakout": f"Never chase {ticker} — enter only on pullbacks after big moves.",
            "pre_earnings_entry": f"Avoid {ticker} entries within 1 day of earnings.",
            "low_volume_breakout": f"Low-volume breakouts in {ticker} are false signals — wait for volume confirmation.",
            "macro_ignored": f"When macro is bearish, {ticker} individual bullish signals don't matter.",
            "poor_rr": f"The R/R on {ticker} was inadequate — skip trades below 2:1.",
            "held_too_long": f"{ticker} reversed after hitting target — always take profit when the plan is hit.",
            "weak_catalyst": f"The {ticker} catalyst was already priced in — only act on fresh, significant catalysts.",
            "unknown": f"Review {ticker} entry criteria — exit reason '{exit_reason}' suggests flawed entry logic.",
        }
        lesson = lesson_map.get(pattern, lesson_map["unknown"])

        return {
            "trade": trade,
            "what_went_wrong": what_went_wrong,
            "which_signal_failed": which_signal_failed,
            "pattern": pattern,
            "adjustment": adjustment,
            "lesson": lesson,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def save_lesson(self, lesson: dict):
        """Append lesson to LESSONS.md and patterns.json."""
        LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)

        trade = lesson["trade"]
        ticker = trade.get("ticker", "?")
        date = trade.get("date", "?")
        pnl_pct = trade.get("pnl_pct", 0)
        exit_reason = trade.get("exit_reason", "?")

        # Initialize LESSONS.md if not exists
        if not LESSONS_FILE.exists():
            LESSONS_FILE.write_text(
                "# CooperCorp Trading — Lessons Learned\n\n"
                "Auto-updated by PostMortem after every losing trade.\n\n"
                "## Active Adjustments (applied to every scan)\n_None yet._\n\n"
                "## Recurring Mistakes (2+ occurrences)\n_None yet._\n\n"
                "## Individual Trade Post-Mortems\n\n"
            )

        # Append new post-mortem entry
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = (
            f"### {date} — {ticker} {pnl_pct:+.1%} — {exit_reason}\n"
            f"**What went wrong:** {lesson['what_went_wrong']}\n"
            f"**Signal that failed:** {lesson['which_signal_failed']}\n"
            f"**Pattern:** `{lesson['pattern']}`\n"
            f"**Adjustment:** {json.dumps(lesson['adjustment'])}\n"
            f"**Lesson:** {lesson['lesson']}\n\n"
            f"---\n\n"
        )

        content = LESSONS_FILE.read_text()
        # Update timestamp line
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("Auto-updated"):
                lines[i] = f"Auto-updated by PostMortem after every losing trade.  \nLast updated: {timestamp}"
                break
        content = "\n".join(lines)

        # Append before end
        LESSONS_FILE.write_text(content + entry)
        logger.info(f"Lesson saved for {ticker}")

        # Update patterns.json
        patterns = self.get_patterns()
        pattern = lesson["pattern"]
        patterns[pattern] = patterns.get(pattern, 0) + 1
        with open(PATTERNS_FILE, "w") as f:
            json.dump(patterns, f, indent=2)

    def get_all_lessons(self) -> list:
        """Return all lessons from LESSONS.md as raw text blocks."""
        if not LESSONS_FILE.exists():
            return []
        content = LESSONS_FILE.read_text()
        # Split by H3 markers
        sections = content.split("### ")
        return [s.strip() for s in sections[1:] if s.strip()]

    def get_patterns(self) -> dict:
        """Returns: {"chased_breakout": 3, "ignored_macro": 1, ...}"""
        if not PATTERNS_FILE.exists():
            return {}
        try:
            with open(PATTERNS_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def analyze_signal_patterns(self):
        """
        Uses signal accuracy stats to enhance post-mortem analysis.

        - If signal accuracy for a specific scan time < 55%: add note to LESSONS.md
        - If signal accuracy for a specific ticker < 50%: add to PatternTracker as "unreliable_ticker"

        Called automatically by the verification cron after each verification pass.
        """
        try:
            from tradingagents.signals.signal_logger import SignalLogger
            from tradingagents.learning.pattern_tracker import PatternTracker
        except ImportError as e:
            logger.warning(f"analyze_signal_patterns: import failed: {e}")
            return

        sl = SignalLogger()
        pt = PatternTracker()
        stats = sl.get_accuracy_stats()

        if stats["verified_signals"] < 5:
            logger.info("analyze_signal_patterns: not enough verified signals yet")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        notes = []

        # Check scan-time accuracy
        for scan_time, data in stats.get("by_scan_time", {}).items():
            if data["count"] >= 3 and data["accuracy"] < 0.55:
                msg = (
                    f"Scan window {scan_time} accuracy is {data['accuracy']*100:.0f}% "
                    f"({data['count']} signals) — below 55% threshold"
                )
                notes.append(msg)
                logger.warning(f"Low scan-time accuracy: {msg}")

        # Check ticker accuracy
        for ticker, data in stats.get("by_ticker", {}).items():
            if data["count"] >= 3 and data["accuracy"] < 0.50:
                msg = (
                    f"Ticker {ticker} accuracy is {data['accuracy']*100:.0f}% "
                    f"({data['count']} signals) — unreliable"
                )
                notes.append(msg)
                logger.warning(f"Unreliable ticker: {msg}")
                # Add to PatternTracker as unreliable_ticker
                try:
                    pt.record_pattern("unreliable_ticker", {
                        "ticker": ticker,
                        "accuracy": data["accuracy"],
                        "signal_count": data["count"],
                        "flagged_at": timestamp,
                    })
                    logger.info(f"PatternTracker updated: {ticker} flagged as unreliable_ticker")
                except Exception as e:
                    logger.warning(f"PatternTracker update failed for {ticker}: {e}")

        # Write to LESSONS.md
        if notes:
            LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not LESSONS_FILE.exists():
                LESSONS_FILE.write_text(
                    "# CooperCorp Trading — Lessons Learned\n\n"
                    "Auto-updated by PostMortem after every losing trade.\n\n"
                    "## Active Adjustments (applied to every scan)\n_None yet._\n\n"
                    "## Recurring Mistakes (2+ occurrences)\n_None yet._\n\n"
                    "## Individual Trade Post-Mortems\n\n"
                )
            existing = LESSONS_FILE.read_text()
            section = (
                f"\n### Signal Pattern Analysis — {timestamp}\n"
                + "\n".join(f"- {n}" for n in notes)
                + "\n\n---\n"
            )
            LESSONS_FILE.write_text(existing + section)
            logger.info(f"analyze_signal_patterns: wrote {len(notes)} notes to LESSONS.md")
        else:
            logger.info("analyze_signal_patterns: all scan times and tickers within acceptable accuracy")
