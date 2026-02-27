#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Signal Verification Cron Job
Runs every 4 hours (M-F) to retroactively verify pending signals.

Cron: 0 */4 * * 1-5 (America/Detroit)

Usage:
    python3 scripts/verify_signals.py
    python3 scripts/verify_signals.py --dry-run
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("verify_signals")


def post_discord_alert(message: str, channel: str = "paper-trades"):
    """Post an alert to Discord via the discord_reporter."""
    try:
        from tradingagents.discord_reporter import DiscordReporter
        reporter = DiscordReporter()
        reporter.send(message, channel=channel)
        logger.info(f"Discord alert sent to #{channel}")
    except Exception as e:
        logger.warning(f"Discord alert failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Verify pending signals retroactively")
    parser.add_argument("--dry-run", action="store_true", help="Log but do not write verifications")
    args = parser.parse_args()

    logger.info("=== Signal Verification Pass Starting ===")
    now = datetime.now(timezone.utc)

    from tradingagents.signals.signal_logger import SignalLogger
    from tradingagents.signals.signal_verifier import SignalVerifier
    from tradingagents.learning.post_mortem import PostMortem

    sl = SignalLogger()
    verifier = SignalVerifier(broker=None, logger_instance=sl)

    # Get pending count before
    pending_before = sl.get_unverified(older_than_hours=4)
    logger.info(f"Pending signals to verify: {len(pending_before)}")

    if args.dry_run:
        logger.info("DRY RUN — no verifications will be written")
        for s in pending_before:
            logger.info(f"  Would verify: {s.get('id')} {s.get('ticker')} {s.get('action')} @ {s.get('price_at_signal')}")
        return

    # Run verification
    verifier.verify_pending()

    # Re-check stats post-verification
    stats = sl.get_accuracy_stats()
    total = stats["total_signals"]
    verified = stats["verified_signals"]

    logger.info(f"Post-verification: {verified}/{total} signals verified")
    logger.info(f"BUY accuracy: {stats['buy_accuracy']:.1%}")
    logger.info(f"SELL accuracy: {stats['sell_accuracy']:.1%}")
    logger.info(f"HOLD accuracy: {stats['hold_accuracy']:.1%}")
    logger.info(f"PASS quality:  {stats['pass_quality']:.1%}")

    # Check if today's accuracy dropped below 50%
    from datetime import timedelta
    today_stats = sl.get_accuracy_stats(days=1)
    today_verified = today_stats["verified_signals"]

    if today_verified >= 3:
        avg_today = (
            today_stats["buy_accuracy"] * 0.4
            + today_stats["sell_accuracy"] * 0.2
            + today_stats["hold_accuracy"] * 0.2
            + today_stats["pass_quality"] * 0.2
        )
        if avg_today < 0.50:
            alert_msg = (
                f"⚠️ **Signal Accuracy Alert** — {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"Today's signal accuracy dropped below 50%: {avg_today:.1%}\n"
                f"BUY: {today_stats['buy_accuracy']:.1%} | "
                f"SELL: {today_stats['sell_accuracy']:.1%} | "
                f"HOLD: {today_stats['hold_accuracy']:.1%} | "
                f"PASS: {today_stats['pass_quality']:.1%}\n"
                f"Verified signals today: {today_verified}"
            )
            logger.warning("Today accuracy below 50% — sending Discord alert")
            post_discord_alert(alert_msg)

    # Run pattern analysis (feeds into LESSONS.md + PatternTracker)
    try:
        pm = PostMortem()
        pm.analyze_signal_patterns()
        logger.info("Pattern analysis complete")
    except Exception as e:
        logger.error(f"Pattern analysis failed: {e}")

    logger.info("=== Signal Verification Pass Complete ===")


if __name__ == "__main__":
    main()
