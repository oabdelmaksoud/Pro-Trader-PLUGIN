#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Trading Dashboard Server
Full real-time: SSE stream for tick-level P&L + polling endpoints.

Usage:
  python3 dashboard/server.py          # default port 8002
  python3 dashboard/server.py --port 8002
  python3 dashboard/server.py --open   # auto-open browser

SSE endpoint: GET /stream
  Pushes JSON events every ~1s during market hours, ~5s otherwise.
  Event types: positions, market, signal, alert, heartbeat
"""
import sys, json, os, time, argparse, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

PORT = 8002

# ── SHARED STATE ─────────────────────────────────────────────────────────────
# Background thread writes here; SSE handler reads and pushes to clients
_state_lock = threading.Lock()
_state = {
    "positions": [],
    "portfolio_value": None,
    "buying_power": None,
    "today_pnl": 0,
    "heat": 0,
    "vix": None,
    "fear_greed": None,
    "sector_momentum": {},
    "btc_signal": {},
    "last_tick": {},        # {symbol: price} from live_prices.json
    "last_updated": 0,
    "last_signal": None,   # most recent signal log entry
    "alerts": [],          # recent alerts for SSE push
    "market_open": False,
    "stream_running": False,
}

_sse_clients: list = []
_sse_lock = threading.Lock()

LIVE_PRICES = REPO / "logs" / "live_prices.json"
SIGNALS_LOG = REPO / "logs" / "signals.jsonl"
LEDGER_LOG  = REPO / "logs" / "ledger.jsonl"
EQUITY_LOG  = REPO / "logs" / "equity_curve.jsonl"


# ── DATA GETTERS ──────────────────────────────────────────────────────────────

def _load_live_prices() -> dict:
    try:
        if LIVE_PRICES.exists():
            raw = json.loads(LIVE_PRICES.read_text())
            # {symbol: {price: float, ts: ...}} or {symbol: float}
            out = {}
            for sym, val in raw.items():
                out[sym] = val["price"] if isinstance(val, dict) else float(val)
            return out
    except Exception:
        pass
    return {}


def _load_signals(days=7, limit=50) -> list:
    try:
        if not SIGNALS_LOG.exists():
            return []
        lines = SIGNALS_LOG.read_text().strip().split("\n")
        items = []
        cutoff = time.time() - days * 86400
        for line in reversed(lines):
            if not line:
                continue
            try:
                d = json.loads(line)
                ts = d.get("ts") or d.get("timestamp", 0)
                if isinstance(ts, str):
                    from datetime import datetime
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


def _load_ledger(days=90) -> list:
    try:
        if not LEDGER_LOG.exists():
            return []
        records = []
        for line in LEDGER_LOG.read_text().strip().split("\n"):
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
        return records
    except Exception:
        return []


def get_account_data():
    from tradingagents.brokers.alpaca import AlpacaBroker
    from tradingagents.risk.portfolio_heat import PortfolioHeat
    broker = AlpacaBroker()
    acct = broker.api.get_account()
    positions = broker.get_positions()
    heat_obj = PortfolioHeat(broker)
    heat_data = heat_obj.get_heat()

    live = _load_live_prices()
    pos_list = []
    today_pnl = 0.0
    for p in positions:
        try:
            sym = p.symbol
            cur = live.get(sym, float(p.current_price))
            entry = float(p.avg_entry_price)
            qty   = float(p.qty)
            unr_pl  = (cur - entry) * qty
            unr_plpc = (cur - entry) / entry if entry else 0
            pos_list.append({
                "symbol": sym,
                "qty": qty,
                "avg_entry_price": str(entry),
                "current_price": str(round(cur, 4)),
                "unrealized_pl": str(round(unr_pl, 2)),
                "unrealized_plpc": str(round(unr_plpc, 6)),
                "market_value": str(round(cur * abs(qty), 2)),
            })
            today_pnl += unr_pl
        except Exception:
            pass

    return {
        "portfolio_value": float(acct.portfolio_value),
        "buying_power": float(acct.buying_power),
        "cash": float(acct.cash),
        "status": acct.status,
        "positions": pos_list,
        "today_pnl": round(today_pnl, 2),
        "heat": heat_data.get("total_pct", 0),
        "heat_by_sector": heat_data.get("by_sector", {}),
    }


def get_context_data():
    from tradingagents.dataflows.fear_greed import get_vix, get_fear_greed
    from tradingagents.dataflows.market_context import get_sector_momentum, get_btc_signal
    return {
        "vix": get_vix(),
        "fear_greed": get_fear_greed(),
        "sector_momentum": get_sector_momentum(),
        "btc_signal": get_btc_signal(),
    }


def get_performance_data():
    try:
        from tradingagents.signals.signal_logger import SignalLogger
        sl = SignalLogger()
        stats = sl.get_accuracy_stats()
        records = _load_ledger()
        wins   = [r for r in records if r.get("pnl_pct", 0) > 0]
        losses = [r for r in records if r.get("pnl_pct", 0) < 0]
        total  = len(records)
        return {
            "win_rate":      len(wins) / total if total else 0,
            "avg_win_pct":   sum(r["pnl_pct"] for r in wins)   / len(wins)   if wins   else 0,
            "avg_loss_pct":  sum(r["pnl_pct"] for r in losses) / len(losses) if losses else 0,
            "total_trades":  total,
            "by_scan_window": stats.get("by_scan_time", {}),
        }
    except Exception as e:
        return {"win_rate": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
                "total_trades": 0, "error": str(e)}


def get_equity_data():
    points = []
    if EQUITY_LOG.exists():
        for line in EQUITY_LOG.read_text().strip().split("\n"):
            if line:
                try:
                    d = json.loads(line)
                    points.append(float(d.get("portfolio_value", 0)))
                except Exception:
                    pass
    return {"points": points[-60:]}


def get_chart_data(ticker: str):
    from tradingagents.discord_signal_card import _fetch_recent_closes, _draw_ascii_chart
    from tradingagents.dataflows.options_chain import get_options_contracts
    import yfinance as yf
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="2d", interval="1d")
        price = float(hist["Close"].iloc[-1])
        prev  = float(hist["Close"].iloc[-2])
        chg   = (price - prev) / prev * 100
        entry = price
        stop  = round(price * 0.97,  2)
        t1    = round(price * 1.08,  2)
        t2    = round(price * 1.14,  2)
        prices    = _fetch_recent_closes(ticker)
        chart     = _draw_ascii_chart(prices, entry, stop, t1, t2, price)
        contracts = get_options_contracts(ticker, "LONG", price)
        return {
            "ticker": ticker, "price": price, "change_pct": round(chg, 2),
            "chart": chart, "entry": entry, "stop": stop, "t1": t1, "t2": t2,
            "contracts": contracts[:3],
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── BACKGROUND REFRESH THREAD ─────────────────────────────────────────────────

def _bg_refresh():
    """
    Runs forever. Two loops:
    - Fast loop (~1s): reads live_prices.json, updates position P&L in _state, broadcasts to SSE
    - Slow loop (~30s): re-fetches Alpaca account + market context, updates _state
    """
    slow_interval = 30
    last_slow = 0
    last_signal_ts = None

    while True:
        try:
            now = time.time()
            live = _load_live_prices()

            with _state_lock:
                _state["last_tick"] = live
                _state["stream_running"] = (REPO / "logs" / "stream.pid").exists()

                # Re-price open positions from live feed if available
                for pos in _state["positions"]:
                    sym = pos["symbol"]
                    if sym in live:
                        cur   = live[sym]
                        entry = float(pos["avg_entry_price"])
                        qty   = float(pos["qty"])
                        pos["current_price"]   = str(round(cur, 4))
                        pos["unrealized_pl"]   = str(round((cur - entry) * qty, 2))
                        pos["unrealized_plpc"] = str(round((cur - entry) / entry, 6))

                # Recalc today P&L
                _state["today_pnl"] = sum(float(p["unrealized_pl"]) for p in _state["positions"])

            # Push positions tick to all SSE clients
            _broadcast("positions", {
                "positions":     _state["positions"],
                "today_pnl":     _state["today_pnl"],
                "portfolio_value": _state["portfolio_value"],
            })

            # Check for new signals
            sigs = _load_signals(days=1, limit=1)
            if sigs:
                latest = sigs[0]
                ts = latest.get("ts") or latest.get("timestamp")
                if ts != last_signal_ts:
                    last_signal_ts = ts
                    _broadcast("signal", latest)
                    with _state_lock:
                        _state["last_signal"] = latest

            # Slow refresh: account + market context
            if now - last_slow > slow_interval:
                last_slow = now
                try:
                    acct = get_account_data()
                    with _state_lock:
                        _state.update({
                            "positions":       acct["positions"],
                            "portfolio_value": acct["portfolio_value"],
                            "buying_power":    acct["buying_power"],
                            "today_pnl":       acct["today_pnl"],
                            "heat":            acct["heat"],
                            "last_updated":    now,
                        })
                    _broadcast("account", acct)
                except Exception:
                    pass

                try:
                    ctx = get_context_data()
                    with _state_lock:
                        _state.update({
                            "vix":              ctx.get("vix"),
                            "fear_greed":       ctx.get("fear_greed"),
                            "sector_momentum":  ctx.get("sector_momentum", {}),
                            "btc_signal":       ctx.get("btc_signal", {}),
                        })
                    _broadcast("market", ctx)
                except Exception:
                    pass

            # Heartbeat
            _broadcast("heartbeat", {"ts": now, "stream": _state["stream_running"]})

        except Exception:
            pass

        # Fast tick: 1s when stream is live, 3s otherwise
        tick = 1.0 if _state.get("stream_running") else 3.0
        time.sleep(tick)


def _broadcast(event_type: str, data: dict):
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode()
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


# ── HTTP HANDLER ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, fpath, content_type="text/html"):
        try:
            content = Path(fpath).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404); self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        # ── Dashboard HTML ──
        if path in ("", "/", "/dashboard"):
            self.send_file(Path(__file__).parent / "index.html")

        # ── SSE real-time stream ──
        elif path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            # Send current state immediately on connect
            with _state_lock:
                snapshot = dict(_state)
            try:
                init = f"event: init\ndata: {json.dumps(snapshot)}\n\n".encode()
                self.wfile.write(init)
                self.wfile.flush()
            except Exception:
                return

            with _sse_lock:
                _sse_clients.append(self)

            # Keep connection open — bg thread does the writing
            try:
                while True:
                    time.sleep(60)
            except Exception:
                pass
            finally:
                with _sse_lock:
                    if self in _sse_clients:
                        _sse_clients.remove(self)

        # ── REST fallbacks ──
        elif path == "/api/account":
            try:   self.send_json(get_account_data())
            except Exception as e: self.send_json({"error": str(e)}, 500)

        elif path == "/api/context":
            try:   self.send_json(get_context_data())
            except Exception as e: self.send_json({"error": str(e)}, 500)

        elif path == "/api/performance":
            try:   self.send_json(get_performance_data())
            except Exception as e: self.send_json({"error": str(e)}, 500)

        elif path == "/api/equity":
            try:   self.send_json(get_equity_data())
            except Exception as e: self.send_json({"error": str(e)}, 500)

        elif path.startswith("/api/chart/"):
            ticker = path.split("/")[-1].upper()
            try:   self.send_json(get_chart_data(ticker))
            except Exception as e: self.send_json({"error": str(e)}, 500)

        elif path == "/api/signals":
            try:
                self.send_json({"signals": _load_signals()})
            except Exception as e: self.send_json({"error": str(e)}, 500)

        elif path == "/api/status":
            from tradingagents.utils.market_hours import is_market_open
            self.send_json({
                "market_open":    is_market_open(),
                "stream_running": _state["stream_running"],
                "sse_clients":    len(_sse_clients),
                "server":         "ok",
            })

        else:
            self.send_response(404); self.end_headers()


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()

    # Prime state with initial Alpaca data (best-effort)
    print("🦅 CooperCorp Dashboard — warming up...")
    try:
        acct = get_account_data()
        with _state_lock:
            _state.update({
                "positions":       acct["positions"],
                "portfolio_value": acct["portfolio_value"],
                "buying_power":    acct["buying_power"],
                "today_pnl":       acct["today_pnl"],
                "heat":            acct["heat"],
            })
        print(f"   Portfolio: ${acct['portfolio_value']:,.2f} | {len(acct['positions'])} positions")
    except Exception as e:
        print(f"   ⚠️  Alpaca unavailable ({e}) — will retry in background")

    # Start background refresh thread
    t = threading.Thread(target=_bg_refresh, daemon=True)
    t.start()

    # Use ThreadingHTTPServer so SSE connections don't block REST calls
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("localhost", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"   Dashboard: {url}")
    print(f"   SSE stream: {url}/stream")
    print(f"   Press Ctrl+C to stop\n")

    if args.open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped")


if __name__ == "__main__":
    main()
