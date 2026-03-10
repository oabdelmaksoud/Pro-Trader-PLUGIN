"""
CooperCorp PRJ-002 — Alpaca WebSocket real-time feed.
Replaces 15-min cron polling with live price updates.
Runs as a background process; exits cleanly on SIGTERM.

Now uses TrailingStopManager + PartialExitManager instead of hardcoded %.
Reads thresholds from config/strategy.json.

Usage (background):
  python3 -m tradingagents.dataflows.alpaca_stream &

The stream writes real-time price ticks to:
  logs/live_prices.json  — {symbol: {price, timestamp, change_pct}}

The position monitor cron reads this file if it exists (falls back to REST).
"""
import asyncio
import json
import os
import signal
import sys
import logging
from pathlib import Path
from datetime import datetime

# Alpaca stream support via alpaca-py
try:
    from alpaca.data.live import StockDataStream, OptionDataStream
    from alpaca.data.models import Bar, Trade, Quote
    ALPACA_PY_AVAILABLE = True
except ImportError:
    ALPACA_PY_AVAILABLE = False

REPO_ROOT = Path(__file__).parent.parent.parent
PRICES_FILE = REPO_ROOT / "logs" / "live_prices.json"
PID_FILE = REPO_ROOT / "logs" / "stream.pid"
STRATEGY_FILE = REPO_ROOT / "config" / "strategy.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [STREAM] %(message)s")
log = logging.getLogger("alpaca_stream")


class AlpacaStream:
    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY", "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self.base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.is_paper = "paper" in self.base_url
        self.prices = {}
        self.running = False
        self.wss_client = None
        self._subscribed = set()
        self._closed_symbols: set = set()  # prevent double-close
        self._trail_mgr = None
        self._partial_mgr = None
        self._strategy = self._load_strategy()

    def _load_strategy(self) -> dict:
        """Load strategy config for thresholds."""
        try:
            return json.loads(STRATEGY_FILE.read_text())
        except Exception:
            return {}

    def _init_risk_managers(self):
        """Initialize trailing stop and partial exit managers."""
        try:
            from tradingagents.risk.trailing_stop import TrailingStopManager
            from tradingagents.risk.partial_exit import PartialExitManager
            trail_pct = self._strategy.get("trailing_stop", {}).get("trail_pct", 0.02)
            self._trail_mgr = TrailingStopManager(trail_pct=trail_pct)
            self._partial_mgr = PartialExitManager()
            log.info(f"Risk managers loaded (trail: {trail_pct*100:.1f}%)")
        except Exception as e:
            log.warning(f"Risk managers not available: {e}")

    def _load_entry_prices(self) -> dict:
        """Load entry prices from open trade files for P&L calculation."""
        entry_prices = {}
        trades_dir = REPO_ROOT / "logs" / "open_trades"
        if trades_dir.exists():
            for f in trades_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    sym = data.get("symbol", f.stem.upper())
                    entry_prices[sym] = float(data.get("entry_price", 0))
                except Exception:
                    pass
        return entry_prices

    def _update_prices_file(self):
        """Write current prices to shared file."""
        try:
            PRICES_FILE.parent.mkdir(parents=True, exist_ok=True)
            PRICES_FILE.write_text(json.dumps(self.prices, indent=2))
        except Exception as e:
            log.warning(f"Failed to write prices file: {e}")

    def get_positions_from_broker(self) -> list:
        """Get current open positions from Alpaca REST."""
        try:
            import sys
            sys.path.insert(0, str(REPO_ROOT))
            from tradingagents.brokers.alpaca import AlpacaBroker
            broker = AlpacaBroker()
            return [p.symbol for p in broker.get_positions()]
        except Exception:
            return []

    async def handle_trade(self, trade):
        """Handle real-time trade tick with dynamic trailing stops."""
        sym = trade.symbol
        price = float(trade.price)
        ts = datetime.now().isoformat()

        # Skip symbols already closed this session
        if sym in self._closed_symbols:
            return

        entry_prices = self._load_entry_prices()
        entry = entry_prices.get(sym, 0)
        change_pct = ((price - entry) / entry * 100) if entry > 0 else 0

        self.prices[sym] = {
            "price": price,
            "timestamp": ts,
            "change_pct": round(change_pct, 3),
            "entry_price": entry,
        }
        self._update_prices_file()

        # Exit checks (only for open positions with known entry)
        if entry <= 0:
            return

        pos_cfg = self._strategy.get("position", {})
        target_pct = pos_cfg.get("target_pct", 0.06) * 100
        stop_pct = pos_cfg.get("stop_pct", 0.02) * 100
        partial_trigger = pos_cfg.get("partial_exit_trigger", 0.04) * 100

        # 1) Trailing stop (dynamic, tightens as price rises)
        if self._trail_mgr:
            stop_price = self._trail_mgr.update(sym, price)
            if price <= stop_price and stop_price > 0:
                log.warning(f"🛑 TRAILING STOP: {sym} ${price:.2f} <= stop ${stop_price:.2f} (HWM: ${self._trail_mgr.get_hwm(sym):.2f})")
                self._closed_symbols.add(sym)
                self._trigger_close(sym, "STOP_HIT")
                return

        # 2) Partial exit at +4% (configurable)
        if self._partial_mgr and not self._partial_mgr.has_taken_partial(sym):
            if change_pct >= partial_trigger:
                log.warning(f"📊 PARTIAL EXIT: {sym} +{change_pct:.1f}% — take 50% off")
                # Don't close here — just alert. Trade gate handles partial.
                self._trigger_partial(sym, price)

        # 3) Hard target
        if change_pct >= target_pct:
            log.warning(f"🎯 TARGET HIT: {sym} +{change_pct:.2f}% — triggering close")
            self._closed_symbols.add(sym)
            self._trigger_close(sym, "TARGET_HIT")

        # 4) Hard stop (backup if trailing stop fails)
        elif change_pct <= -stop_pct:
            log.warning(f"🛑 STOP HIT: {sym} {change_pct:.2f}% — triggering close")
            self._closed_symbols.add(sym)
            self._trigger_close(sym, "STOP_HIT")

    def _trigger_close(self, sym: str, reason: str):
        """Trigger close_position.py for a symbol."""
        import subprocess
        try:
            result = subprocess.Popen([
                sys.executable,
                str(REPO_ROOT / "scripts" / "close_position.py"),
                "--ticker", sym,
                "--reason", reason,
            ])
            log.info(f"Triggered close_position.py for {sym} ({reason}) PID={result.pid}")
        except Exception as e:
            log.error(f"Failed to trigger close for {sym}: {e}")

    def _trigger_partial(self, sym: str, price: float):
        """Trigger partial exit (50% off) via close_position.py."""
        import subprocess
        try:
            result = subprocess.Popen([
                sys.executable,
                str(REPO_ROOT / "scripts" / "close_position.py"),
                "--ticker", sym,
                "--reason", "PARTIAL_EXIT",
                "--exit-price", str(price),
            ])
            log.info(f"Triggered partial exit for {sym} at ${price:.2f} PID={result.pid}")
            if self._partial_mgr:
                self._partial_mgr.mark_partial_taken(sym, price, 0)
        except Exception as e:
            log.error(f"Failed to trigger partial for {sym}: {e}")

    async def run(self, symbols: list = None):
        """Start the WebSocket stream."""
        if not ALPACA_PY_AVAILABLE:
            log.error("alpaca-py not installed. Run: pip3 install alpaca-py --break-system-packages")
            return

        if not self.api_key or not self.secret_key:
            log.error("ALPACA_API_KEY or ALPACA_SECRET_KEY not set")
            return

        # Get symbols from open positions if not specified
        if not symbols:
            symbols = self.get_positions_from_broker()
            if not symbols:
                log.info("No open positions to stream. Waiting for positions...")
                # Poll every 60s for new positions
                while self.running:
                    await asyncio.sleep(60)
                    symbols = self.get_positions_from_broker()
                    if symbols:
                        break
                if not symbols:
                    return

        # Init risk managers
        self._init_risk_managers()

        log.info(f"Starting stream for: {symbols}")

        # Write PID file
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        # Split symbols: options have long OCC-format names (>6 chars typically)
        def is_option(sym: str) -> bool:
            # OCC option symbols are 21 chars: e.g. NVDA260313P00175000
            return len(sym) > 10 and any(c in sym for c in ('P', 'C')) and sym[-8:].isdigit()

        stock_syms = [s for s in symbols if not is_option(s)]
        option_syms = [s for s in symbols if is_option(s)]

        if option_syms:
            log.info(f"Options detected (will use OptionDataStream): {option_syms}")
        if stock_syms:
            log.info(f"Stocks (will use StockDataStream): {stock_syms}")

        if not stock_syms and not option_syms:
            log.warning("No valid symbols to stream.")
            return

        tasks = []

        try:
            if stock_syms:
                wss = StockDataStream(
                    api_key=self.api_key,
                    secret_key=self.secret_key,
                    feed="iex",  # iex = free tier real-time; use "sip" for paid
                )
                for sym in stock_syms:
                    wss.subscribe_trades(self.handle_trade, sym)
                    self._subscribed.add(sym)
                    log.info(f"Subscribed to {sym} stock trades")
                self.wss_client = wss
                tasks.append(asyncio.create_task(wss._run_forever()))

            if option_syms:
                owss = OptionDataStream(
                    api_key=self.api_key,
                    secret_key=self.secret_key,
                )
                for sym in option_syms:
                    owss.subscribe_trades(self.handle_trade, sym)
                    self._subscribed.add(sym)
                    log.info(f"Subscribed to {sym} option trades")
                tasks.append(asyncio.create_task(owss._run_forever()))

            self.running = True
            log.info("Stream running. Press Ctrl+C to stop.")
            if tasks:
                await asyncio.gather(*tasks)

        except Exception as e:
            log.error(f"Stream error: {e}")
        finally:
            if PID_FILE.exists():
                PID_FILE.unlink()
            log.info("Stream stopped")

    def stop(self):
        self.running = False
        if self.wss_client:
            try:
                self.wss_client.stop()
            except Exception:
                pass


def main():
    """Entry point for running as a background process."""
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")

    stream = AlpacaStream()

    def handle_shutdown(signum, frame):
        log.info(f"Received signal {signum}, shutting down...")
        stream.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Parse optional symbol list from args
    symbols = sys.argv[1:] if len(sys.argv) > 1 else None

    asyncio.run(stream.run(symbols))


if __name__ == "__main__":
    main()
