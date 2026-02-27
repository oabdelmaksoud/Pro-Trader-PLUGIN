"""
CooperCorp PRJ-002 — Signal Verifier
Retroactively verifies signals by checking actual price movement.
Runs every 4 hours to verify past signals that are old enough to evaluate.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from tradingagents.signals.signal_logger import SignalLogger

logger = logging.getLogger(__name__)


class SignalVerifier:
    """
    Retroactively verifies signals by checking actual price movement.
    Runs every 4 hours to verify past signals.
    """

    def __init__(self, broker=None, logger_instance: Optional[SignalLogger] = None):
        self.broker = broker
        self.signal_logger = logger_instance or SignalLogger()

    def _fetch_bars(self, ticker: str, signal_date: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV bars for ticker on the signal date.
        Falls back to yfinance if broker data is unavailable.

        Returns a DataFrame with columns: open, high, low, close, volume
        indexed by timestamp, or None on failure.
        """
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            # Fetch intraday 5-min bars for that day
            bars = stock.history(
                start=signal_date,
                end=signal_date,
                interval="5m",
                prepost=False,
            )
            if bars.empty:
                # Try daily bars as fallback
                bars = stock.history(start=signal_date, end=signal_date, interval="1d")
            return bars if not bars.empty else None
        except Exception as e:
            logger.warning(f"yfinance fetch failed for {ticker} on {signal_date}: {e}")
            return None

    def _get_price_at_offset(self, bars: pd.DataFrame, signal_ts: datetime, hours: int) -> Optional[float]:
        """
        Get closing price approximately `hours` hours after signal_ts.
        Returns None if no bars are available in that window.
        """
        if bars is None or bars.empty:
            return None

        target_ts = signal_ts + pd.Timedelta(hours=hours)
        # Find the bar closest to target_ts
        try:
            # Normalize index timezone
            idx = bars.index
            if idx.tz is None:
                idx = idx.tz_localize("America/New_York")
            else:
                idx = idx.tz_convert("America/New_York")

            target_ts_local = target_ts.astimezone(
                __import__("pytz").timezone("America/New_York")
            )
            diffs = abs(idx - target_ts_local)
            closest = diffs.argmin()
            return float(bars.iloc[closest]["Close"])
        except Exception as e:
            logger.debug(f"Price-at-offset lookup failed: {e}")
            return None

    def verify_pending(self):
        """
        For each unverified signal older than 4 hours:
        1. Fetch actual OHLCV data for that ticker on that date
        2. Check: did price move in the direction of the signal?
        3. Did it hit the target? Did it hit the stop?
        4. Mark as verified with results
        """
        pending = self.signal_logger.get_unverified(older_than_hours=4)
        logger.info(f"SignalVerifier: {len(pending)} pending signals to verify")

        for signal in pending:
            signal_id = signal.get("id")
            ticker = signal.get("ticker", "")
            try:
                ts_str = signal["timestamp"].replace("Z", "+00:00")
                signal_ts = datetime.fromisoformat(ts_str)
            except Exception:
                logger.warning(f"Bad timestamp for signal {signal_id}, skipping")
                continue

            signal_date = signal_ts.strftime("%Y-%m-%d")
            bars = self._fetch_bars(ticker, signal_date)

            if bars is None:
                logger.warning(f"No bar data for {ticker} on {signal_date} — skipping {signal_id}")
                continue

            verification = self._check_signal_accuracy(signal, bars)
            self.signal_logger.mark_verified(signal_id, verification)
            logger.info(
                f"Verified {signal_id}: {ticker} {signal.get('action')} — "
                f"correct={verification.get('signal_correct')} "
                f"accuracy={verification.get('accuracy_pct'):.2f}%"
                if verification.get("accuracy_pct") is not None
                else f"Verified {signal_id}: {ticker} {signal.get('action')}"
            )

    def _check_signal_accuracy(self, signal: dict, bars: pd.DataFrame) -> dict:
        """
        Evaluate whether the signal direction was correct.

        For a BUY signal at price X:
        - Correct if price went up and hit target before stop
        - Partially correct if price went up but didn't hit target
        - Wrong if stop was hit before target

        For a SELL signal at price X:
        - Correct if price went down (toward stop_loss direction)
        - Wrong if price went up

        For a PASS/HOLD signal:
        - Correct if price stayed flat or went down (good call to skip)
        - Wrong if price went up significantly (missed opportunity)

        Returns verification dict with keys:
            price_1h_later, price_4h_later, price_eod,
            target_hit, stop_hit, signal_correct, accuracy_pct
        """
        action = signal.get("action", "").upper()
        entry_price = float(signal.get("price_at_signal", 0) or 0)
        target = signal.get("target")
        stop_loss = signal.get("stop_loss")

        try:
            ts_str = signal["timestamp"].replace("Z", "+00:00")
            signal_ts = datetime.fromisoformat(ts_str)
        except Exception:
            signal_ts = datetime.now(timezone.utc)

        price_1h = self._get_price_at_offset(bars, signal_ts, 1)
        price_4h = self._get_price_at_offset(bars, signal_ts, 4)

        # EOD: last bar of the day
        try:
            price_eod = float(bars.iloc[-1]["Close"])
        except Exception:
            price_eod = None

        # Evaluate target/stop hit using intraday high/low
        target_hit = None
        stop_hit = None
        signal_correct = None
        accuracy_pct = None

        if entry_price > 0:
            # Check if target/stop were hit using bar extremes
            if target and stop_loss:
                try:
                    day_high = float(bars["High"].max())
                    day_low = float(bars["Low"].min())

                    if action == "BUY":
                        target_hit = day_high >= float(target)
                        stop_hit = day_low <= float(stop_loss)
                    elif action == "SELL":
                        # For SELL: target is below entry, stop is above entry
                        target_hit = day_low <= float(target)
                        stop_hit = day_high >= float(stop_loss)
                except Exception as e:
                    logger.debug(f"Target/stop check failed: {e}")

            # Compute accuracy_pct: price change in direction of signal
            ref_price = price_eod or price_4h or price_1h
            if ref_price and entry_price:
                raw_change = (ref_price - entry_price) / entry_price * 100

                if action == "BUY":
                    accuracy_pct = round(raw_change, 4)  # positive = correct
                    if target_hit is not None and stop_hit is not None:
                        # Correct: target hit and stop not hit first
                        signal_correct = target_hit and not stop_hit
                    else:
                        # Fallback: just directionally correct
                        signal_correct = raw_change > 0

                elif action == "SELL":
                    accuracy_pct = round(-raw_change, 4)  # price drop = positive
                    if target_hit is not None and stop_hit is not None:
                        signal_correct = target_hit and not stop_hit
                    else:
                        signal_correct = raw_change < 0

                elif action in ("PASS", "HOLD"):
                    accuracy_pct = round(-raw_change, 4)  # price drop = good call
                    # Correct if price went down or stayed flat (within 1%)
                    signal_correct = raw_change <= 1.0

        return {
            "price_1h_later": price_1h,
            "price_4h_later": price_4h,
            "price_eod": price_eod,
            "target_hit": target_hit,
            "stop_hit": stop_hit,
            "signal_correct": signal_correct,
            "accuracy_pct": accuracy_pct,
        }
