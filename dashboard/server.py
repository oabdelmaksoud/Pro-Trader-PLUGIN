#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Trading Dashboard Server
Serves live data from Alpaca + market sources to the HTML dashboard.

Usage:
  python3 dashboard/server.py          # default port 8002
  python3 dashboard/server.py --port 8002
  python3 dashboard/server.py --open   # auto-open browser
"""
import sys, json, os, argparse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

PORT = 8002


def get_account_data():
    from tradingagents.brokers.alpaca import AlpacaBroker
    from tradingagents.risk.portfolio_heat import PortfolioHeat
    broker = AlpacaBroker()
    acct = broker.api.get_account()
    positions = broker.get_positions()
    heat = PortfolioHeat(broker)
    heat_data = heat.get_heat()

    pos_list = []
    today_pnl = 0
    for p in positions:
        try:
            pos_list.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": str(p.avg_entry_price),
                "current_price": str(p.current_price),
                "unrealized_pl": str(p.unrealized_pl),
                "unrealized_plpc": str(float(p.unrealized_plpc)),
                "market_value": str(p.market_value),
            })
            today_pnl += float(p.unrealized_pl)
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
    from tradingagents.signals.signal_logger import SignalLogger
    from tradingagents.performance.ledger import TradeLedger
    try:
        sl = SignalLogger()
        stats = sl.get_accuracy_stats()
        ledger = TradeLedger()
        ledger_file = REPO / "logs" / "ledger.jsonl"
        records = []
        if ledger_file.exists():
            for line in ledger_file.read_text().strip().split("\n"):
                if line:
                    try: records.append(json.loads(line))
                    except: pass
        wins = [r for r in records if r.get("pnl_pct", 0) > 0]
        losses = [r for r in records if r.get("pnl_pct", 0) < 0]
        total = len(records)
        win_rate = len(wins) / total if total > 0 else 0
        avg_win = sum(r.get("pnl_pct", 0) for r in wins) / len(wins) if wins else 0
        avg_loss = sum(r.get("pnl_pct", 0) for r in losses) / len(losses) if losses else 0
        by_window = stats.get("by_scan_time", {})
        return {
            "win_rate": win_rate,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "total_trades": total,
            "by_scan_window": by_window,
        }
    except Exception as e:
        return {"win_rate": 0, "avg_win_pct": 0, "avg_loss_pct": 0, "total_trades": 0, "error": str(e)}


def get_equity_data():
    equity_file = REPO / "logs" / "equity_curve.jsonl"
    points = []
    if equity_file.exists():
        for line in equity_file.read_text().strip().split("\n"):
            if line:
                try:
                    d = json.loads(line)
                    points.append(float(d.get("portfolio_value", 0)))
                except Exception:
                    pass
    return {"points": points[-60:] if points else []}  # last 60 days


def get_chart_data(ticker: str):
    from tradingagents.discord_signal_card import format_signal_card, _fetch_recent_closes, _draw_ascii_chart
    from tradingagents.dataflows.options_chain import get_options_contracts
    import yfinance as yf
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="2d", interval="1d")
        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        chg = (price - prev) / prev * 100
        entry = price
        stop = round(price * 0.97, 2)
        t1 = round(price * 1.08, 2)
        t2 = round(price * 1.14, 2)
        prices = _fetch_recent_closes(ticker)
        chart = _draw_ascii_chart(prices, entry, stop, t1, t2, price)
        contracts = get_options_contracts(ticker, "LONG", price)
        return {
            "ticker": ticker,
            "price": price,
            "change_pct": round(chg, 2),
            "chart": chart,
            "entry": entry,
            "stop": stop,
            "t1": t1,
            "t2": t2,
            "contracts": contracts[:3],
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # quiet

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type="text/html"):
        try:
            content = Path(path).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path in ("", "/", "/dashboard"):
            self.send_file(Path(__file__).parent / "index.html")

        elif path == "/api/account":
            try:
                self.send_json(get_account_data())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/api/context":
            try:
                self.send_json(get_context_data())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/api/performance":
            try:
                self.send_json(get_performance_data())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/api/equity":
            try:
                self.send_json(get_equity_data())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path.startswith("/api/chart/"):
            ticker = path.split("/")[-1].upper()
            try:
                self.send_json(get_chart_data(ticker))
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/api/signals":
            try:
                from tradingagents.signals.signal_logger import SignalLogger
                sl = SignalLogger()
                sigs = sl.get_signals(days=7)
                self.send_json({"signals": sigs[-50:]})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/api/status":
            from tradingagents.utils.market_hours import is_market_open
            stream_pid = REPO / "logs" / "stream.pid"
            self.send_json({
                "market_open": is_market_open(),
                "stream_running": stream_pid.exists(),
                "server": "ok",
            })

        else:
            self.send_response(404)
            self.end_headers()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()

    server = HTTPServer(("localhost", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"🦅 CooperCorp Dashboard running at {url}")
    print(f"   Press Ctrl+C to stop")

    if args.open_browser:
        import webbrowser, threading
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped")


if __name__ == "__main__":
    main()
