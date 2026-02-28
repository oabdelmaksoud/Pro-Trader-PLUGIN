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
        by_ticker = {}
        for r in records:
            sym = r.get("ticker") or r.get("symbol","")
            if not sym: continue
            if sym not in by_ticker: by_ticker[sym] = {"wins":0,"total":0,"accuracy":0}
            by_ticker[sym]["total"] += 1
            if r.get("pnl_pct",0)>0: by_ticker[sym]["wins"]+=1
        for v in by_ticker.values():
            v["accuracy"] = v["wins"]/v["total"] if v["total"] else 0
        return {
            "win_rate":      len(wins) / total if total else 0,
            "avg_win_pct":   sum(r["pnl_pct"] for r in wins)   / len(wins)   if wins   else 0,
            "avg_loss_pct":  sum(r["pnl_pct"] for r in losses) / len(losses) if losses else 0,
            "total_trades":  total,
            "by_scan_window": stats.get("by_scan_time", {}),
            "by_ticker": by_ticker,
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


def get_chart_data(ticker: str, direction: str = "LONG", score: float = 7.0):
    from tradingagents.discord_signal_card import _fetch_recent_closes, _draw_ascii_chart
    from tradingagents.dataflows.options_chain import get_options_strategies
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
        prices = _fetch_recent_closes(ticker)
        chart  = _draw_ascii_chart(prices, entry, stop, t1, t2, price, height=14, width=56)
        from tradingagents.dataflows.iv_percentile import get_iv_rank
        from tradingagents.dataflows.relative_strength import get_relative_strength
        iv_data = {}; rs_data = {}
        try: iv_data = get_iv_rank(ticker)
        except: pass
        try: rs_data = get_relative_strength(ticker)
        except: pass
        iv_rank = iv_data.get("iv_rank")
        strategies = get_options_strategies(
            ticker, direction=direction, current_price=price,
            iv_rank=iv_rank, score=score
        )
        return {
            "ticker": ticker, "price": price, "change_pct": round(chg, 2),
            "chart": chart, "entry": entry, "stop": stop, "t1": t1, "t2": t2,
            "strategies": strategies,
            "directional": strategies.get("directional", [])[:3],
            "neutral":     strategies.get("neutral", [])[:2],
            "income":      strategies.get("income", [])[:2],
            "best_strategy": strategies.get("best_strategy", ""),
            "summary": strategies.get("summary", ""),
            "contracts": strategies.get("all", [])[:3],
            "iv_rank": iv_rank,
            "iv_ok": iv_data.get("ok_to_buy_options"),
            "rs": rs_data.get("rs_ratio"),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


# ── NEWS / MOVERS / EARNINGS / WATCHLIST ──────────────────────────────────────

def _get_news(limit=25, tickers=None) -> list:
    """Aggregated news from 6 sources via news_aggregator."""
    try:
        from tradingagents.dataflows.news_aggregator import get_news
        raw = get_news(tickers=tickers, limit=limit)
        items = []
        for n in raw:
            sent_raw = n.get("sentiment","neutral")
            sent = "bull" if sent_raw == "bullish" else "bear" if sent_raw == "bearish" else "neut"
            items.append({
                "source":    n.get("source","").split("/")[0][:15],
                "title":     n.get("title",""),
                "url":       n.get("url",""),
                "time":      n.get("published_fmt",""),
                "sentiment": sent,
                "relevance": n.get("relevance",0),
                "tickers":   n.get("tickers",[]),
            })
        return items
    except Exception:
        # Legacy fallback
        items = []
        try:
            from tradingagents.dataflows.finnhub_data import get_market_news
            news = get_market_news() or []
            for n in news[:10]:
                items.append({"source":"Finnhub","title":n.get("headline",""),"time":_fmt_ts(n.get("datetime",0)),"sentiment":None})
        except Exception: pass
        try:
            from tradingagents.dataflows.newsapi_data import get_top_news
            na = get_top_news(query="stock market") or []
            for n in na[:5]:
                items.append({"source":"NewsAPI","title":n.get("title",""),"time":"","sentiment":None})
        except Exception: pass
        return [i for i in items if i.get("title")][:limit]

def _fmt_ts(ts) -> str:
    try:
        import datetime
        if isinstance(ts, (int,float)) and ts > 1e9:
            return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")
        if isinstance(ts, str) and "T" in ts:
            return ts[11:16]
    except Exception: pass
    return ""

def _get_movers(limit=10) -> list:
    try:
        from tradingagents.dataflows.polygon_data import get_top_movers
        raw = get_top_movers() or []
        out = []
        for m in raw[:limit]:
            out.append({"symbol": m.get("ticker",""),"change_pct": m.get("todaysChangePerc",0),"vol_ratio": None,"category":"mover"})
        return out
    except Exception:
        return []

def _get_earnings_and_squeeze() -> dict:
    from datetime import datetime, timedelta
    earnings = []
    try:
        from tradingagents.dataflows.earnings_whisper import get_earnings_calendar
        cal = get_earnings_calendar() or []
        today = datetime.now().date()
        for e in cal[:10]:
            try:
                d = datetime.strptime(e.get("date",""), "%Y-%m-%d").date()
                days = (d - today).days
                earnings.append({"symbol":e.get("symbol",""),"date":str(d),"est_eps":e.get("eps_estimate"),"days":days})
            except Exception: pass
    except Exception: pass

    squeeze = []
    try:
        from tradingagents.dataflows.short_interest import get_short_interest
        for ticker in ["NVDA","AMD","TSLA","MSTR","PLTR","GME","AMC"]:
            si = get_short_interest(ticker)
            if si and si.get("short_pct",0) > 15:
                squeeze.append({"symbol":ticker,"short_pct":si.get("short_pct"),"borrow_rate":si.get("borrow_rate")})
    except Exception: pass

    return {"earnings": earnings, "squeeze": squeeze}

def _get_trades_and_patterns() -> dict:
    trades = []
    records = []
    if LEDGER_LOG.exists():
        for line in LEDGER_LOG.read_text().strip().split("\n"):
            if line:
                try: records.append(json.loads(line))
                except: pass
    for r in records:
        trades.append({
            "ticker": r.get("ticker") or r.get("symbol",""),
            "side": r.get("side","BUY"),
            "entry_price": r.get("entry_price",0),
            "exit_price": r.get("exit_price",0),
            "pnl_pct": r.get("pnl_pct",0),
            "pnl_usd": r.get("pnl_usd",0),
            "scan_time": r.get("scan_time",""),
            "close_time": r.get("close_time",""),
        })

    # Pattern tracker
    patterns = []
    try:
        from tradingagents.performance.pattern_tracker import PatternTracker
        pt = PatternTracker()
        raw = pt.get_patterns()
        for name, data in (raw or {}).items():
            patterns.append({"name":name,"count":data.get("count",0),"status":data.get("status","tracking")})
        patterns.sort(key=lambda x: x["count"], reverse=True)
    except Exception: pass

    # By-ticker stats
    by_ticker = {}
    for t in records:
        sym = t.get("ticker") or t.get("symbol","")
        if not sym: continue
        if sym not in by_ticker: by_ticker[sym] = {"wins":0,"total":0}
        by_ticker[sym]["total"] += 1
        if t.get("pnl_pct",0) > 0: by_ticker[sym]["wins"] += 1
    for v in by_ticker.values():
        v["accuracy"] = v["wins"]/v["total"] if v["total"] else 0

    return {"trades": trades, "patterns": patterns, "by_ticker": by_ticker}

def _get_watchlist_item(ticker: str) -> dict:
    import yfinance as yf
    from tradingagents.dataflows.iv_percentile import get_iv_rank
    from tradingagents.dataflows.relative_strength import get_relative_strength
    from tradingagents.dataflows.short_interest import get_short_interest
    from datetime import datetime, timedelta

    tk = yf.Ticker(ticker)
    hist = tk.history(period="30d", interval="1d")
    if hist.empty:
        return {"ticker": ticker, "error": "no data"}

    price = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2]) if len(hist)>1 else price
    chg = (price-prev)/prev*100

    # Technicals
    closes = hist["Close"].tolist()
    vols = hist["Volume"].tolist()
    vol_ratio = vols[-1] / (sum(vols[-21:-1])/20) if len(vols)>20 else 1.0

    # MACD
    def ema(data, n):
        k=2/(n+1); e=data[0]
        for d in data[1:]: e=d*k+e*(1-k)
        return e
    macd_cross = False
    if len(closes)>=26:
        ema12=ema(closes[-12:],12); ema26=ema(closes[-26:],26)
        macd=ema12-ema26
        prev_macd=ema(closes[-13:-1],12)-ema(closes[-27:-1],26)
        macd_cross = macd>0 and prev_macd<=0

    # BB
    import statistics
    bb_squeeze = False
    if len(closes)>=20:
        m20=sum(closes[-20:])/20; std=statistics.stdev(closes[-20:])
        bb_upper=m20+2*std; bb_lower=m20-2*std
        bb_width=(bb_upper-bb_lower)/m20
        bb_squeeze = bb_width < 0.04

    # IV rank
    iv_data = {}
    try: iv_data = get_iv_rank(ticker)
    except: pass

    # RS
    rs_data = {}
    try: rs_data = get_relative_strength(ticker)
    except: pass

    # Short interest
    si = {}
    try: si = get_short_interest(ticker) or {}
    except: pass

    # Pre-score (simplified)
    pre_score = 5.0
    if macd_cross: pre_score += 0.7
    if bb_squeeze: pre_score += 0.4
    if vol_ratio > 2: pre_score += 0.5
    elif vol_ratio > 1.5: pre_score += 0.3

    # Earnings countdown
    earnings_days = None
    try:
        cal = tk.calendar
        if cal is not None and not cal.empty:
            earn_date = cal.columns[0]
            earnings_days = (earn_date.date() - datetime.now().date()).days
    except: pass

    return {
        "ticker": ticker,
        "price": price,
        "change_pct": round(chg, 2),
        "vol_ratio": round(vol_ratio, 2),
        "macd_cross": macd_cross,
        "bb_squeeze": bb_squeeze,
        "pre_score": round(pre_score, 1),
        "iv_rank": iv_data.get("iv_rank"),
        "iv_cheap": iv_data.get("ok_to_buy_options", False),
        "rs": rs_data.get("rs_ratio"),
        "short_pct": si.get("short_pct"),
        "squeeze_candidate": (si.get("short_pct") or 0) > 15,
        "earnings_days": earnings_days,
    }


# ── BACKGROUND REFRESH THREAD ─────────────────────────────────────────────────

def _check_milestones(portfolio_value: float):
    """Fire once when portfolio crosses 25/50/75% of $1M target."""
    try:
        START  = 100499
        TARGET = 1_000_000
        milestones = {
            0.25: ("🎯 25% TO GOAL", 325499),
            0.50: ("🚀 HALFWAY THERE", 550499),
            0.75: ("🦅 75% TO GOAL — ALMOST THERE", 775499),
        }
        mpath = REPO / "logs" / "milestones.json"
        fired = set(json.load(open(mpath))) if mpath.exists() else set()

        for pct, (label, threshold) in milestones.items():
            key = f"{pct:.2f}"
            if key not in fired and portfolio_value >= threshold:
                fired.add(key)
                gain_pct = (portfolio_value - START) / START * 100
                msg = (
                    f"{label} 🎉\n\n"
                    f"Portfolio: ${portfolio_value:,.2f}\n"
                    f"Gain: +{gain_pct:.1f}% from ${START:,}\n"
                    f"Progress: ${portfolio_value:,.0f} / $1,000,000\n"
                    f"Remaining: ${TARGET - portfolio_value:,.0f}\n"
                    f"— Cooper 🦅 | PRJ-002"
                )
                import subprocess
                subprocess.Popen([
                    "openclaw", "message", "send",
                    "--channel", "discord",
                    "--target", "1469763123010342953",
                    "--message", msg,
                ])
                mpath.write_text(json.dumps(list(fired)))
                _broadcast("milestone", {"label": label, "value": portfolio_value, "pct": pct})
    except Exception:
        pass


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
                    _check_milestones(acct["portfolio_value"])
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

        elif path == "/api/news":
            try:
                items = _get_news()
                self.send_json({"items": items})
            except Exception as e:
                self.send_json({"items": [], "error": str(e)})

        elif path == "/api/movers":
            try:
                movers = _get_movers()
                self.send_json({"movers": movers})
            except Exception as e:
                self.send_json({"movers": [], "error": str(e)})

        elif path == "/api/earnings":
            try:
                data = _get_earnings_and_squeeze()
                self.send_json(data)
            except Exception as e:
                self.send_json({"earnings": [], "squeeze": [], "error": str(e)})

        elif path == "/api/trades":
            try:
                self.send_json(_get_trades_and_patterns())
            except Exception as e:
                self.send_json({"trades": [], "patterns": [], "error": str(e)})

        elif path.startswith("/api/watchlist/"):
            ticker = path.split("/")[-1].upper()
            try:
                self.send_json(_get_watchlist_item(ticker))
            except Exception as e:
                self.send_json({"ticker": ticker, "error": str(e)})

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
