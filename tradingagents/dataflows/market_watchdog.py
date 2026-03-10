"""
CooperCorp PRJ-002 — Real-Time Market Watchdog
Watches the ENTIRE watchlist via Alpaca WebSocket — like having your eyes
on every chart simultaneously.

Detects:
  - Flash crashes:   >2% drop in <60 seconds
  - Momentum surges: >3% move in <5 minutes
  - Volume spikes:   3× rolling average in 1 minute
  - Trailing stop breaches on open positions
  - Partial exit triggers (+4%) on open positions

Alerts go to Discord instantly via openclaw CLI.
Writes real-time data to logs/watchdog_prices.json for dashboard.

Usage:
  python3 -m tradingagents.dataflows.market_watchdog          # all watchlist
  python3 -m tradingagents.dataflows.market_watchdog NVDA AMD # specific tickers
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import logging
import time
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

try:
    from alpaca.data.live import StockDataStream
    ALPACA_PY_AVAILABLE = True
except ImportError:
    ALPACA_PY_AVAILABLE = False

REPO_ROOT = Path(__file__).parent.parent.parent
PRICES_FILE = REPO_ROOT / "logs" / "watchdog_prices.json"
PID_FILE = REPO_ROOT / "logs" / "watchdog.pid"
ALERTS_FILE = REPO_ROOT / "logs" / "watchdog_alerts.json"
STRATEGY_FILE = REPO_ROOT / "config" / "strategy.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
)
log = logging.getLogger("market_watchdog")

# ---------------------------------------------------------------------------
# Alert thresholds (configurable)
# ---------------------------------------------------------------------------
FLASH_CRASH_PCT = -2.0      # % drop in <60s
FLASH_CRASH_WINDOW = 60     # seconds
MOMENTUM_SURGE_PCT = 3.0    # % move in <5 min
MOMENTUM_WINDOW = 300       # seconds
VOLUME_SPIKE_MULT = 3.0     # 3× average 1-min volume
VOLUME_WINDOW = 60          # seconds for volume bucket
VOLUME_BASELINE_MINS = 15   # baseline = average of last N 1-min buckets
ALERT_COOLDOWN = 300        # don't re-alert same ticker+type within 5 min


class TickBuffer:
    """Rolling buffer of (timestamp, price, size) tuples for one symbol."""

    def __init__(self, max_age: int = 900):
        self.ticks: deque = deque()
        self.max_age = max_age  # keep 15 min of ticks
        self.open_price: float = 0.0  # first price of the day (or session)
        self.prev_close: float = 0.0
        self.volume_buckets: deque = deque(maxlen=VOLUME_BASELINE_MINS)
        self._current_bucket_ts: int = 0
        self._current_bucket_vol: int = 0

    def add(self, ts: float, price: float, size: int):
        self.ticks.append((ts, price, size))
        if self.open_price == 0:
            self.open_price = price
        # Prune old ticks
        cutoff = ts - self.max_age
        while self.ticks and self.ticks[0][0] < cutoff:
            self.ticks.popleft()
        # Volume bucketing (1-min buckets)
        bucket = int(ts // VOLUME_WINDOW)
        if bucket != self._current_bucket_ts:
            if self._current_bucket_ts > 0:
                self.volume_buckets.append(self._current_bucket_vol)
            self._current_bucket_ts = bucket
            self._current_bucket_vol = size
        else:
            self._current_bucket_vol += size

    @property
    def latest_price(self) -> float:
        return self.ticks[-1][1] if self.ticks else 0.0

    @property
    def latest_ts(self) -> float:
        return self.ticks[-1][0] if self.ticks else 0.0

    def price_at(self, seconds_ago: float) -> float:
        """Get the price ~N seconds ago (earliest tick in that window)."""
        if not self.ticks:
            return 0.0
        cutoff = self.latest_ts - seconds_ago
        for ts, price, _ in self.ticks:
            if ts >= cutoff:
                return price
        return self.ticks[0][1]

    def pct_change(self, seconds: float) -> float:
        """% change over last N seconds."""
        old = self.price_at(seconds)
        if old <= 0:
            return 0.0
        return ((self.latest_price - old) / old) * 100

    def avg_volume_per_min(self) -> float:
        """Average volume per 1-min bucket over baseline window."""
        if not self.volume_buckets:
            return 0.0
        return sum(self.volume_buckets) / len(self.volume_buckets)


class MarketWatchdog:
    """
    Real-time market monitor via Alpaca WebSocket.
    Watches all watchlist tickers + open positions simultaneously.
    """

    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY", "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self.base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.buffers: dict[str, TickBuffer] = {}
        self.prices: dict = {}
        self.running = False
        self.wss_client = None
        self._alert_cooldowns: dict[str, float] = {}  # "SYM:type" -> last_alert_ts
        self._recent_alerts: deque = deque(maxlen=100)
        self._entry_prices: dict[str, float] = {}
        self._trail_mgr = None
        self._partial_mgr = None

    def _load_watchlist(self) -> list[str]:
        """Load all watchlist tickers from strategy.json."""
        try:
            cfg = json.loads(STRATEGY_FILE.read_text())
            wl = cfg.get("watchlist", {})
            symbols = set()
            for key, val in wl.items():
                if key.startswith("_"):
                    continue
                if isinstance(val, list):
                    symbols.update(v.upper() for v in val)
            return sorted(symbols)
        except Exception as e:
            log.warning(f"Failed to load watchlist: {e}")
            return []

    def _load_open_positions(self) -> list[str]:
        """Get symbols with open trades."""
        syms = []
        trades_dir = REPO_ROOT / "logs" / "open_trades"
        if trades_dir.exists():
            for f in trades_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    sym = data.get("symbol", f.stem.upper())
                    self._entry_prices[sym] = float(data.get("entry_price", 0))
                    syms.append(sym)
                except Exception:
                    pass
        return syms

    def _init_risk_managers(self):
        """Load trailing stop and partial exit managers."""
        try:
            from tradingagents.risk.trailing_stop import TrailingStopManager
            from tradingagents.risk.partial_exit import PartialExitManager
            cfg = json.loads(STRATEGY_FILE.read_text())
            trail_pct = cfg.get("trailing_stop", {}).get("trail_pct", 0.02)
            self._trail_mgr = TrailingStopManager(trail_pct=trail_pct)
            self._partial_mgr = PartialExitManager()
        except Exception as e:
            log.warning(f"Risk managers not loaded: {e}")

    def _send_alert(self, sym: str, alert_type: str, message: str):
        """Send Discord alert via openclaw CLI (with cooldown)."""
        key = f"{sym}:{alert_type}"
        now = time.time()
        if key in self._alert_cooldowns:
            if now - self._alert_cooldowns[key] < ALERT_COOLDOWN:
                return  # still in cooldown
        self._alert_cooldowns[key] = now

        alert = {
            "symbol": sym,
            "type": alert_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._recent_alerts.append(alert)

        # Write alerts file for dashboard
        try:
            ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            ALERTS_FILE.write_text(json.dumps(list(self._recent_alerts), indent=2))
        except Exception:
            pass

        log.warning(f"ALERT [{alert_type}] {sym}: {message}")

        # Post to Discord via openclaw
        try:
            subprocess.Popen(
                ["openclaw", "message", "send",
                 "--channel", "discord",
                 "--target", "war-room",
                 "--message", f"🚨 **{alert_type}** | {sym}\n{message}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass  # openclaw not installed

    def _trigger_close(self, sym: str, reason: str):
        """Trigger position close."""
        try:
            subprocess.Popen([
                sys.executable,
                str(REPO_ROOT / "scripts" / "close_position.py"),
                "--ticker", sym,
                "--reason", reason,
            ])
            log.info(f"Triggered close for {sym} ({reason})")
        except Exception as e:
            log.error(f"Failed to trigger close for {sym}: {e}")

    def _check_alerts(self, sym: str, buf: TickBuffer):
        """Run all alert checks for a symbol after each tick."""
        price = buf.latest_price

        # --- 1) Flash crash: >2% drop in <60s ---
        change_60s = buf.pct_change(FLASH_CRASH_WINDOW)
        if change_60s <= FLASH_CRASH_PCT:
            self._send_alert(
                sym, "FLASH_CRASH",
                f"${price:.2f} — dropped {change_60s:.1f}% in <{FLASH_CRASH_WINDOW}s"
            )

        # --- 2) Momentum surge: >3% move in <5 min ---
        change_5m = buf.pct_change(MOMENTUM_WINDOW)
        if abs(change_5m) >= MOMENTUM_SURGE_PCT:
            direction = "UP" if change_5m > 0 else "DOWN"
            self._send_alert(
                sym, f"MOMENTUM_{direction}",
                f"${price:.2f} — moved {change_5m:+.1f}% in <5 min"
            )

        # --- 3) Volume spike: 3× average 1-min volume ---
        avg_vol = buf.avg_volume_per_min()
        if avg_vol > 0 and buf._current_bucket_vol > avg_vol * VOLUME_SPIKE_MULT:
            spike = buf._current_bucket_vol / avg_vol
            self._send_alert(
                sym, "VOLUME_SPIKE",
                f"${price:.2f} — volume {spike:.1f}× normal ({buf._current_bucket_vol:,} vs avg {int(avg_vol):,})"
            )

        # --- 4) Open position checks ---
        entry = self._entry_prices.get(sym, 0)
        if entry <= 0:
            return

        change_pct = ((price - entry) / entry) * 100

        # 4a) Trailing stop check
        if self._trail_mgr:
            stop_price = self._trail_mgr.update(sym, price)
            if price <= stop_price and stop_price > 0:
                self._send_alert(
                    sym, "TRAILING_STOP",
                    f"${price:.2f} breached trailing stop ${stop_price:.2f} (HWM: ${self._trail_mgr.get_hwm(sym):.2f})"
                )
                self._trigger_close(sym, "STOP_HIT")

        # 4b) Partial exit trigger
        cfg = {}
        try:
            cfg = json.loads(STRATEGY_FILE.read_text()).get("position", {})
        except Exception:
            pass
        partial_trigger = cfg.get("partial_exit_trigger", 0.04) * 100  # 4%
        if self._partial_mgr and not self._partial_mgr.has_taken_partial(sym):
            if change_pct >= partial_trigger:
                self._send_alert(
                    sym, "PARTIAL_EXIT",
                    f"${price:.2f} — up {change_pct:.1f}% from entry ${entry:.2f} — take 50% off"
                )

        # 4c) Hard target hit
        target_pct = cfg.get("target_pct", 0.06) * 100  # 6%
        if change_pct >= target_pct:
            self._send_alert(
                sym, "TARGET_HIT",
                f"${price:.2f} — up {change_pct:.1f}% — TARGET reached"
            )
            self._trigger_close(sym, "TARGET_HIT")

        # 4d) Hard stop hit (backup — trailing stop should catch first)
        stop_pct = cfg.get("stop_pct", 0.02) * 100  # 2%
        if change_pct <= -stop_pct:
            self._send_alert(
                sym, "HARD_STOP",
                f"${price:.2f} — down {change_pct:.1f}% — STOP hit"
            )
            self._trigger_close(sym, "STOP_HIT")

    async def handle_trade(self, trade):
        """Process every real-time trade tick."""
        sym = trade.symbol
        price = float(trade.price)
        size = int(trade.size) if hasattr(trade, 'size') else 1
        ts = time.time()

        if sym not in self.buffers:
            self.buffers[sym] = TickBuffer()
        self.buffers[sym].add(ts, price, size)

        # Update shared prices file
        buf = self.buffers[sym]
        entry = self._entry_prices.get(sym, 0)
        change_pct = ((price - entry) / entry * 100) if entry > 0 else 0
        day_change = ((price - buf.open_price) / buf.open_price * 100) if buf.open_price > 0 else 0

        self.prices[sym] = {
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "change_pct": round(change_pct, 3),
            "day_change_pct": round(day_change, 3),
            "entry_price": entry,
            "open_price": buf.open_price,
            "volume_1m": buf._current_bucket_vol,
        }

        # Write prices file periodically (every 50 ticks to reduce I/O)
        if len(self.buffers) > 0 and sum(len(b.ticks) for b in self.buffers.values()) % 50 == 0:
            self._write_prices()

        # Run alert checks
        self._check_alerts(sym, buf)

    def _write_prices(self):
        try:
            PRICES_FILE.parent.mkdir(parents=True, exist_ok=True)
            PRICES_FILE.write_text(json.dumps(self.prices, indent=2))
        except Exception as e:
            log.warning(f"Failed to write prices: {e}")

    async def run(self, symbols: list = None):
        """Start the watchdog WebSocket stream."""
        if not ALPACA_PY_AVAILABLE:
            log.error("alpaca-py not installed. Run: pip3 install alpaca-py")
            return

        if not self.api_key or not self.secret_key:
            log.error("ALPACA_API_KEY or ALPACA_SECRET_KEY not set")
            return

        # Combine watchlist + open positions
        if symbols:
            all_symbols = [s.upper() for s in symbols]
        else:
            watchlist = self._load_watchlist()
            open_pos = self._load_open_positions()
            all_symbols = sorted(set(watchlist + open_pos))

        if not all_symbols:
            log.error("No symbols to watch")
            return

        # Init risk managers
        self._init_risk_managers()
        # Reload entry prices
        self._load_open_positions()

        log.info(f"Watchdog starting for {len(all_symbols)} symbols: {', '.join(all_symbols[:10])}{'...' if len(all_symbols) > 10 else ''}")

        # Write PID
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        try:
            wss = StockDataStream(
                api_key=self.api_key,
                secret_key=self.secret_key,
                feed="iex",  # free tier real-time
            )

            for sym in all_symbols:
                wss.subscribe_trades(self.handle_trade, sym)
                log.info(f"Subscribed: {sym}")

            self.wss_client = wss
            self.running = True

            # Periodically refresh open positions (check for new entries)
            async def refresh_positions():
                while self.running:
                    await asyncio.sleep(60)
                    self._load_open_positions()

            asyncio.ensure_future(refresh_positions())

            # Periodic price file flush
            async def flush_prices():
                while self.running:
                    await asyncio.sleep(5)
                    self._write_prices()

            asyncio.ensure_future(flush_prices())

            log.info("Watchdog running. Ctrl+C to stop.")
            await wss._run_forever()

        except Exception as e:
            log.error(f"Watchdog error: {e}")
        finally:
            if PID_FILE.exists():
                PID_FILE.unlink()
            self._write_prices()
            log.info("Watchdog stopped")

    def stop(self):
        self.running = False
        if self.wss_client:
            try:
                self.wss_client.stop()
            except Exception:
                pass


def main():
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")

    watchdog = MarketWatchdog()

    def handle_shutdown(signum, frame):
        log.info(f"Received signal {signum}, shutting down...")
        watchdog.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    symbols = sys.argv[1:] if len(sys.argv) > 1 else None
    asyncio.run(watchdog.run(symbols))


if __name__ == "__main__":
    main()
