#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Alpaca WebSocket Stream Manager
Start/stop/status the real-time price stream.

Usage:
  python3 scripts/stream_manager.py start          # start for open positions
  python3 scripts/stream_manager.py start NVDA AMD # start for specific tickers
  python3 scripts/stream_manager.py stop
  python3 scripts/stream_manager.py status
"""
import sys, os, subprocess, json
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

PID_FILE = REPO / "logs" / "stream.pid"
PRICES_FILE = REPO / "logs" / "live_prices.json"
LOG_FILE = REPO / "logs" / "stream.log"


def start(symbols: list = None):
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            print(f"Stream already running (PID {pid})")
            return
        except ProcessLookupError:
            PID_FILE.unlink()

    cmd = [sys.executable, "-m", "tradingagents.dataflows.alpaca_stream"]
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
    print(f"Stream started (PID {proc.pid})")
    print(f"Log: {LOG_FILE}")
    print(f"Prices: {PRICES_FILE}")


def stop():
    if not PID_FILE.exists():
        print("Stream not running")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 15)  # SIGTERM
        PID_FILE.unlink()
        print(f"Stream stopped (PID {pid})")
    except ProcessLookupError:
        PID_FILE.unlink()
        print(f"Stream was not running (PID {pid} not found)")


def status():
    running = False
    pid = None
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)
            running = True
        except ProcessLookupError:
            pass

    print(f"Stream: {'✅ RUNNING' if running else '❌ STOPPED'}" + (f" (PID {pid})" if running else ""))

    if PRICES_FILE.exists():
        try:
            prices = json.loads(PRICES_FILE.read_text())
            if prices:
                print(f"\nLive Prices ({len(prices)} symbols):")
                for sym, data in prices.items():
                    pct = data.get("change_pct", 0)
                    print(f"  {sym}: ${data['price']:.2f} | P&L: {pct:+.2f}% | {data.get('timestamp','')[:19]}")
            else:
                print("No live prices yet")
        except Exception as e:
            print(f"Error reading prices: {e}")
    else:
        print("No prices file (stream not yet publishing)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    symbols = sys.argv[2:] if len(sys.argv) > 2 else None

    if cmd == "start":
        start(symbols)
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    else:
        print(f"Usage: {sys.argv[0]} start|stop|status [TICKER ...]")
