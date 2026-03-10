#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Market Watchdog Manager
Start/stop/status the real-time market watchdog that monitors your entire
watchlist like you're watching every chart live.

Usage:
  python3 scripts/watchdog_manager.py start              # all watchlist tickers
  python3 scripts/watchdog_manager.py start NVDA AMD TSLA # specific tickers
  python3 scripts/watchdog_manager.py stop
  python3 scripts/watchdog_manager.py status
  python3 scripts/watchdog_manager.py alerts              # recent alerts
"""
import sys
import os
import subprocess
import json
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

PID_FILE = REPO / "logs" / "watchdog.pid"
PRICES_FILE = REPO / "logs" / "watchdog_prices.json"
ALERTS_FILE = REPO / "logs" / "watchdog_alerts.json"
LOG_FILE = REPO / "logs" / "watchdog.log"


def start(symbols: list = None):
    """Start the watchdog as a background process."""
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            print(f"Watchdog already running (PID {pid})")
            return
        except ProcessLookupError:
            PID_FILE.unlink()

    cmd = [sys.executable, "-m", "tradingagents.dataflows.market_watchdog"]
    if symbols:
        cmd.extend(symbols)

    log_fd = open(LOG_FILE, "a")
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO),
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,
    )
    print(f"Watchdog started (PID {proc.pid})")
    print(f"Log:    {LOG_FILE}")
    print(f"Prices: {PRICES_FILE}")
    print(f"Alerts: {ALERTS_FILE}")
    print()
    print("Monitoring entire watchlist in real-time.")
    print("Alert types: FLASH_CRASH, MOMENTUM_UP/DOWN, VOLUME_SPIKE,")
    print("             TRAILING_STOP, PARTIAL_EXIT, TARGET_HIT, HARD_STOP")


def stop():
    """Stop the watchdog."""
    if not PID_FILE.exists():
        print("Watchdog not running")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 15)  # SIGTERM
        PID_FILE.unlink()
        print(f"Watchdog stopped (PID {pid})")
    except ProcessLookupError:
        PID_FILE.unlink()
        print(f"Watchdog was not running (PID {pid} not found)")


def status():
    """Show watchdog status and live prices."""
    running = False
    pid = None
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            running = True
        except ProcessLookupError:
            pass

    icon = "RUNNING" if running else "STOPPED"
    print(f"Watchdog: {'✅ ' + icon if running else '❌ ' + icon}" +
          (f" (PID {pid})" if running else ""))

    if PRICES_FILE.exists():
        try:
            prices = json.loads(PRICES_FILE.read_text())
            if prices:
                print(f"\nLive Prices ({len(prices)} symbols):")
                # Sort by absolute day change
                sorted_syms = sorted(
                    prices.items(),
                    key=lambda x: abs(x[1].get("day_change_pct", 0)),
                    reverse=True,
                )
                for sym, data in sorted_syms[:20]:  # top 20 movers
                    day_pct = data.get("day_change_pct", 0)
                    entry_pct = data.get("change_pct", 0)
                    price = data.get("price", 0)
                    vol = data.get("volume_1m", 0)
                    arrow = "▲" if day_pct > 0 else "▼" if day_pct < 0 else "—"
                    pos_tag = f" | P&L: {entry_pct:+.2f}%" if data.get("entry_price", 0) > 0 else ""
                    print(f"  {sym:>6} {arrow} ${price:<8.2f} day: {day_pct:+.2f}%{pos_tag}  vol/m: {vol:,}")
                if len(prices) > 20:
                    print(f"  ... and {len(prices) - 20} more")
            else:
                print("No live prices yet")
        except Exception as e:
            print(f"Error reading prices: {e}")
    else:
        print("No prices file (watchdog not yet publishing)")


def alerts():
    """Show recent watchdog alerts."""
    if not ALERTS_FILE.exists():
        print("No alerts yet")
        return

    try:
        data = json.loads(ALERTS_FILE.read_text())
        if not data:
            print("No alerts yet")
            return
        print(f"Recent Alerts ({len(data)} total):")
        for a in data[-15:]:  # last 15
            ts = a.get("timestamp", "")[:19]
            sym = a.get("symbol", "???")
            atype = a.get("type", "???")
            msg = a.get("message", "")
            icon = {
                "FLASH_CRASH": "💥",
                "MOMENTUM_UP": "🚀",
                "MOMENTUM_DOWN": "📉",
                "VOLUME_SPIKE": "📊",
                "TRAILING_STOP": "🛑",
                "PARTIAL_EXIT": "📊",
                "TARGET_HIT": "🎯",
                "HARD_STOP": "🛑",
            }.get(atype, "⚠️")
            print(f"  {icon} [{ts}] {sym:>6} {atype}: {msg}")
    except Exception as e:
        print(f"Error reading alerts: {e}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    symbols = sys.argv[2:] if len(sys.argv) > 2 else None

    if cmd == "start":
        start(symbols)
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    elif cmd == "alerts":
        alerts()
    else:
        print(f"Usage: {sys.argv[0]} start|stop|status|alerts [TICKER ...]")
