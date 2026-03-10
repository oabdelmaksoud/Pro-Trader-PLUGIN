"""
Pro-Trader Dashboard Server — plugin-aware real-time trading dashboard.

Pulls all data through the pro_trader plugin system:
  - BrokerPlugin  → portfolio, positions
  - DataPlugin    → live quotes, technicals
  - MonitorPlugin → alerts, market conditions
  - AnalystPlugin → recent analysis reports
  - Events        → signal history

Usage:
    pro-trader dashboard              # default port 8080
    pro-trader dashboard --port 9000
    pro-trader dashboard --open       # auto-open browser

SSE endpoint: GET /stream
  Pushes JSON events every ~1-3s: positions, market, signal, alert, heartbeat
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent.parent.parent
DASHBOARD_DIR = Path(__file__).resolve().parent
LOGS_DIR = REPO / "logs"

SIGNALS_LOG = LOGS_DIR / "signals.jsonl"
LEDGER_LOG = LOGS_DIR / "ledger.jsonl"
EQUITY_LOG = LOGS_DIR / "equity_curve.jsonl"
LIVE_PRICES = LOGS_DIR / "live_prices.json"

# ── SHARED STATE ────────────────────────────────────────────────────────────

_state_lock = threading.Lock()
_state: dict = {
    "positions": [],
    "portfolio_value": 0,
    "cash": 0,
    "buying_power": 0,
    "equity": 0,
    "today_pnl": 0,
    "heat": 0,
    "last_tick": {},
    "last_updated": 0,
    "last_signal": None,
    "market_open": False,
    "stream_running": False,
    "plugins": {},
}

_sse_clients: list = []
_sse_lock = threading.Lock()

# Global references set by start()
_trader = None
_config: dict = {}


# ── DATA LOADERS ────────────────────────────────────────────────────────────

def _load_live_prices() -> dict:
    """Load tick prices from live_prices.json (written by streaming plugin)."""
    try:
        if LIVE_PRICES.exists():
            raw = json.loads(LIVE_PRICES.read_text())
            out = {}
            for sym, val in raw.items():
                out[sym] = val["price"] if isinstance(val, dict) else float(val)
            return out
    except Exception:
        pass
    return {}


def _load_jsonl(path: Path, days: int = 7, limit: int = 50) -> list[dict]:
    """Load recent entries from a JSONL log file."""
    try:
        if not path.exists():
            return []
        lines = path.read_text().strip().split("\n")
        items = []
        cutoff = time.time() - days * 86400
        for line in reversed(lines):
            if not line:
                continue
            try:
                d = json.loads(line)
                ts = d.get("ts") or d.get("timestamp", 0)
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts).timestamp()
                    except Exception:
                        ts = 0
                if ts >= cutoff:
                    items.append(d)
                if len(items) >= limit:
                    break
            except Exception:
                pass
        return items
    except Exception:
        return []


def _load_all_jsonl(path: Path) -> list[dict]:
    """Load all entries from a JSONL file."""
    try:
        if not path.exists():
            return []
        records = []
        for line in path.read_text().strip().split("\n"):
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
        return records
    except Exception:
        return []


# ── PLUGIN-AWARE DATA GETTERS ───────────────────────────────────────────────

def _get_portfolio() -> dict:
    """Get portfolio data through BrokerPlugin."""
    if not _trader:
        return {}
    try:
        brokers = _trader.plugins.get_plugins("broker")
        if not brokers:
            return {}
        broker = brokers[0]
        portfolio = broker.get_portfolio()
        positions = []
        live = _load_live_prices()
        today_pnl = 0.0

        for p in portfolio.positions:
            cur = live.get(p.symbol, p.current_price)
            entry = p.avg_entry
            qty = p.qty
            unr_pl = (cur - entry) * qty if entry else 0
            unr_plpc = ((cur - entry) / entry * 100) if entry else 0
            mkt_val = cur * abs(qty)

            positions.append({
                "symbol": p.symbol,
                "qty": qty,
                "avg_entry_price": round(entry, 4),
                "current_price": round(cur, 4),
                "unrealized_pl": round(unr_pl, 2),
                "unrealized_plpc": round(unr_plpc, 2),
                "market_value": round(mkt_val, 2),
                "side": p.side,
                "asset_type": p.asset_type,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
            })
            today_pnl += unr_pl

        return {
            "positions": positions,
            "portfolio_value": portfolio.equity,
            "cash": portfolio.cash,
            "equity": portfolio.equity,
            "buying_power": portfolio.buying_power,
            "today_pnl": round(portfolio.today_pnl or today_pnl, 2),
            "heat": portfolio.heat,
        }
    except Exception as e:
        logger.debug(f"Portfolio fetch failed: {e}")
        return {}


def _get_signals() -> list[dict]:
    """Load recent signals from log."""
    return _load_jsonl(SIGNALS_LOG, days=7, limit=50)


def _get_performance() -> dict:
    """Compute trading performance stats from ledger."""
    records = _load_all_jsonl(LEDGER_LOG)
    if not records:
        return {"win_rate": 0, "avg_win_pct": 0, "avg_loss_pct": 0, "total_trades": 0, "by_ticker": {}}

    wins = [r for r in records if r.get("pnl_pct", 0) > 0]
    losses = [r for r in records if r.get("pnl_pct", 0) < 0]
    total = len(records)

    by_ticker: dict = {}
    for r in records:
        sym = r.get("ticker") or r.get("symbol", "")
        if not sym:
            continue
        if sym not in by_ticker:
            by_ticker[sym] = {"wins": 0, "losses": 0, "total": 0, "total_pnl_pct": 0}
        by_ticker[sym]["total"] += 1
        by_ticker[sym]["total_pnl_pct"] += r.get("pnl_pct", 0)
        if r.get("pnl_pct", 0) > 0:
            by_ticker[sym]["wins"] += 1
        else:
            by_ticker[sym]["losses"] += 1

    for v in by_ticker.values():
        v["win_rate"] = round(v["wins"] / v["total"] * 100, 1) if v["total"] else 0

    return {
        "win_rate": round(len(wins) / total * 100, 1) if total else 0,
        "avg_win_pct": round(sum(r["pnl_pct"] for r in wins) / len(wins), 2) if wins else 0,
        "avg_loss_pct": round(sum(r["pnl_pct"] for r in losses) / len(losses), 2) if losses else 0,
        "total_trades": total,
        "by_ticker": by_ticker,
    }


def _get_equity_curve() -> dict:
    """Load equity curve data points."""
    points = []
    if EQUITY_LOG.exists():
        for line in EQUITY_LOG.read_text().strip().split("\n"):
            if line:
                try:
                    d = json.loads(line)
                    points.append({
                        "value": float(d.get("portfolio_value", 0)),
                        "ts": d.get("ts") or d.get("timestamp", ""),
                    })
                except Exception:
                    pass
    return {"points": points[-120:]}


def _get_trades() -> list[dict]:
    """Load trade ledger."""
    records = _load_all_jsonl(LEDGER_LOG)
    trades = []
    for r in records:
        trades.append({
            "ticker": r.get("ticker") or r.get("symbol", ""),
            "side": r.get("side", "BUY"),
            "entry_price": r.get("entry_price", 0),
            "exit_price": r.get("exit_price", 0),
            "pnl_pct": r.get("pnl_pct", 0),
            "pnl_usd": r.get("pnl_usd", 0),
            "scan_time": r.get("scan_time", ""),
            "close_time": r.get("close_time", ""),
        })
    return trades


def _get_monitors() -> list[dict]:
    """Run all monitor plugins and collect alerts."""
    if not _trader:
        return []
    alerts = []
    try:
        monitors = _trader.plugins.get_plugins("monitor")
        for m in monitors:
            try:
                results = m.check()
                for alert in results:
                    alert["monitor"] = m.name
                    alerts.append(alert)
            except Exception as e:
                logger.debug(f"Monitor {m.name} check failed: {e}")
    except Exception:
        pass
    return alerts


def _get_plugin_health() -> dict:
    """Get health status of all plugins."""
    if not _trader:
        return {}
    try:
        return _trader.health()
    except Exception:
        return {}


def _get_quote(symbol: str) -> dict:
    """Get quote for a symbol through DataPlugin."""
    if not _trader:
        return {}
    try:
        data_plugins = _trader.plugins.get_plugins("data")
        for dp in data_plugins:
            if dp.supports(symbol):
                quote = dp.get_quote(symbol)
                if quote:
                    return {
                        "symbol": quote.symbol,
                        "price": quote.price,
                        "change": quote.change,
                        "change_pct": quote.change_pct,
                        "volume": quote.volume,
                        "avg_volume": quote.avg_volume,
                        "bid": quote.bid,
                        "ask": quote.ask,
                        "high": quote.high,
                        "low": quote.low,
                        "open": quote.open,
                        "prev_close": quote.prev_close,
                        "source": quote.source,
                        "volume_ratio": round(quote.volume_ratio, 2),
                    }
    except Exception as e:
        logger.debug(f"Quote fetch for {symbol} failed: {e}")
    return {}


def _get_technicals(symbol: str) -> dict:
    """Get technicals for a symbol through DataPlugin."""
    if not _trader:
        return {}
    try:
        data_plugins = _trader.plugins.get_plugins("data")
        for dp in data_plugins:
            if dp.supports(symbol):
                tech = dp.get_technicals(symbol)
                if tech:
                    return tech.to_dict()
    except Exception as e:
        logger.debug(f"Technicals fetch for {symbol} failed: {e}")
    return {}


# ── SSE BROADCAST ───────────────────────────────────────────────────────────

def _broadcast(event_type: str, data: dict):
    """Send event to all connected SSE clients."""
    msg = f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n".encode()
    dead = []
    with _sse_lock:
        for client in _sse_clients:
            try:
                client.wfile.write(msg)
                client.wfile.flush()
            except Exception:
                dead.append(client)
        for d in dead:
            _sse_clients.remove(d)


# ── BACKGROUND THREAD ──────────────────────────────────────────────────────

def _bg_refresh():
    """Background thread: fast tick (1-3s) for prices, slow (30s) for full refresh."""
    slow_interval = 30
    last_slow = 0
    last_signal_ts = None

    while True:
        try:
            now = time.time()
            live = _load_live_prices()

            with _state_lock:
                _state["last_tick"] = live
                _state["stream_running"] = (LOGS_DIR / "stream.pid").exists()

                # Re-price positions from live feed
                for pos in _state["positions"]:
                    sym = pos["symbol"]
                    if sym in live:
                        cur = live[sym]
                        entry = float(pos["avg_entry_price"])
                        qty = float(pos["qty"])
                        pos["current_price"] = round(cur, 4)
                        pos["unrealized_pl"] = round((cur - entry) * qty, 2)
                        pos["unrealized_plpc"] = round((cur - entry) / entry * 100, 2) if entry else 0

                _state["today_pnl"] = sum(
                    float(p.get("unrealized_pl", 0)) for p in _state["positions"]
                )

            # Push positions tick
            _broadcast("positions", {
                "positions": _state["positions"],
                "today_pnl": _state["today_pnl"],
                "portfolio_value": _state["portfolio_value"],
            })

            # Check for new signals
            sigs = _load_jsonl(SIGNALS_LOG, days=1, limit=1)
            if sigs:
                latest = sigs[0]
                ts = latest.get("ts") or latest.get("timestamp")
                if ts != last_signal_ts:
                    last_signal_ts = ts
                    _broadcast("signal", latest)
                    with _state_lock:
                        _state["last_signal"] = latest

            # Slow refresh: portfolio + monitors
            if now - last_slow > slow_interval:
                last_slow = now
                try:
                    portfolio = _get_portfolio()
                    if portfolio:
                        with _state_lock:
                            _state.update({
                                "positions": portfolio.get("positions", []),
                                "portfolio_value": portfolio.get("portfolio_value", 0),
                                "cash": portfolio.get("cash", 0),
                                "equity": portfolio.get("equity", 0),
                                "buying_power": portfolio.get("buying_power", 0),
                                "today_pnl": portfolio.get("today_pnl", 0),
                                "heat": portfolio.get("heat", 0),
                                "last_updated": now,
                            })
                        _broadcast("account", portfolio)
                except Exception:
                    pass

                # Monitor alerts
                try:
                    alerts = _get_monitors()
                    if alerts:
                        _broadcast("alerts", {"alerts": alerts})
                except Exception:
                    pass

            # Heartbeat
            _broadcast("heartbeat", {"ts": now, "stream": _state["stream_running"]})

        except Exception:
            pass

        tick = 1.0 if _state.get("stream_running") else 3.0
        time.sleep(tick)


# ── HTTP HANDLER ────────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the trading dashboard."""

    def log_message(self, fmt, *args):
        pass  # Suppress default logging

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, content: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # ── Dashboard HTML ──
        if path in ("", "/", "/dashboard"):
            html_file = DASHBOARD_DIR / "index.html"
            if html_file.exists():
                self._send_html(html_file.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()

        # ── SSE stream ──
        elif path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            # Send current state on connect
            with _state_lock:
                snapshot = dict(_state)
            try:
                init = f"event: init\ndata: {json.dumps(snapshot, default=str)}\n\n".encode()
                self.wfile.write(init)
                self.wfile.flush()
            except Exception:
                return

            with _sse_lock:
                _sse_clients.append(self)

            try:
                while True:
                    time.sleep(60)
            except Exception:
                pass
            finally:
                with _sse_lock:
                    if self in _sse_clients:
                        _sse_clients.remove(self)

        # ── REST API ──
        elif path == "/api/portfolio":
            try:
                self._send_json(_get_portfolio() or _state)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/signals":
            try:
                self._send_json({"signals": _get_signals()})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/performance":
            try:
                self._send_json(_get_performance())
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/equity":
            try:
                self._send_json(_get_equity_curve())
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/trades":
            try:
                self._send_json({"trades": _get_trades()})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/monitors":
            try:
                self._send_json({"alerts": _get_monitors()})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/plugins":
            try:
                self._send_json(_get_plugin_health())
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/quote/"):
            symbol = path.split("/")[-1].upper()
            try:
                self._send_json(_get_quote(symbol))
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/technicals/"):
            symbol = path.split("/")[-1].upper()
            try:
                self._send_json(_get_technicals(symbol))
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/status":
            self._send_json({
                "server": "ok",
                "stream_running": _state["stream_running"],
                "sse_clients": len(_sse_clients),
                "last_updated": _state["last_updated"],
                "plugin_count": len(_state.get("plugins", {})),
            })

        else:
            self.send_response(404)
            self.end_headers()


# ── PUBLIC API ──────────────────────────────────────────────────────────────

def start(port: int = 8080, open_browser: bool = False, trader=None):
    """Start the dashboard server.

    Args:
        port: HTTP port to listen on
        open_browser: Open browser automatically
        trader: ProTrader instance (provides plugin access)
    """
    global _trader
    _trader = trader

    print("Pro-Trader Dashboard — starting...")

    # Prime state with initial portfolio data
    try:
        portfolio = _get_portfolio()
        if portfolio:
            with _state_lock:
                _state.update({
                    "positions": portfolio.get("positions", []),
                    "portfolio_value": portfolio.get("portfolio_value", 0),
                    "cash": portfolio.get("cash", 0),
                    "equity": portfolio.get("equity", 0),
                    "buying_power": portfolio.get("buying_power", 0),
                    "today_pnl": portfolio.get("today_pnl", 0),
                    "heat": portfolio.get("heat", 0),
                })
            pos_count = len(portfolio.get("positions", []))
            pv = portfolio.get("portfolio_value", 0)
            print(f"  Portfolio: ${pv:,.2f} | {pos_count} positions")
    except Exception as e:
        print(f"  Broker unavailable ({e}) — will retry in background")

    # Get plugin status
    try:
        health = _get_plugin_health()
        with _state_lock:
            _state["plugins"] = health
        total = sum(len(v) for v in health.values())
        print(f"  Plugins: {total} loaded")
    except Exception:
        pass

    # Start background thread
    t = threading.Thread(target=_bg_refresh, daemon=True)
    t.start()

    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    url = f"http://localhost:{port}"
    print(f"  Dashboard: {url}")
    print(f"  SSE stream: {url}/stream")
    print(f"  API: {url}/api/portfolio")
    print(f"  Press Ctrl+C to stop\n")

    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped")
        server.server_close()
