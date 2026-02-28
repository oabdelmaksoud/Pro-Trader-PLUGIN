"""
CooperCorp PRJ-002 — Real-Time Quote Layer
Replaces yfinance for live price data. Priority:
  1. Alpaca REST (real-time IEX, free) — US equities + crypto
  2. Finnhub (real-time free tier)     — equities, forex, crypto
  3. Polygon.io (15-min delay free)    — fallback
  4. yfinance                          — last resort (delayed)

Futures proxies (Alpaca/Finnhub don't support CME futures):
  ES=F  → SPY  (S&P 500 ETF, ~0.1× multiplier)
  NQ=F  → QQQ  (Nasdaq ETF)
  YM=F  → DIA  (Dow ETF)
  GC=F  → GLD  (Gold ETF, price × ~9.3 to get spot ≈)
  SI=F  → SLV  (Silver ETF)
  DX-Y.NYB → UUP (Dollar ETF)

Usage:
    from tradingagents.dataflows.realtime_quotes import get_quote, get_quotes

    q = get_quote("NVDA")
    # {'symbol': 'NVDA', 'price': 184.89, 'change': -5.46, 'change_pct': -2.87,
    #  'volume': 123456, 'source': 'alpaca', 'delayed': False}

    qs = get_quotes(["NVDA", "AAPL", "BTC/USD"])
"""
import os
import time
import requests
from typing import Optional
from functools import lru_cache
from pathlib import Path

# Auto-load .env from repo root
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

# ── Futures/commodity proxy map ──────────────────────────────────────────────
PROXY_MAP = {
    "ES=F":      {"proxy": "SPY",  "label": "S&P 500 Futures",  "scale": 10.0},
    "NQ=F":      {"proxy": "QQQ",  "label": "Nasdaq Futures",    "scale": 40.0},
    "YM=F":      {"proxy": "DIA",  "label": "Dow Futures",       "scale": 100.0},
    "GC=F":      {"proxy": "GLD",  "label": "Gold",              "scale": 9.3},
    "SI=F":      {"proxy": "SLV",  "label": "Silver",            "scale": 1.0},
    "DX-Y.NYB":  {"proxy": "UUP",  "label": "US Dollar Index",   "scale": None},
    "TLT":       {"proxy": "TLT",  "label": "Bonds (TLT)",       "scale": None},
    "BTC-USD":   {"proxy": "BTC/USD", "label": "Bitcoin",        "scale": None},
    "ETH-USD":   {"proxy": "ETH/USD", "label": "Ethereum",       "scale": None},
}

# Crypto symbol mapping for Alpaca
CRYPTO_SYMBOLS = {"BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD"}


# ── Alpaca ────────────────────────────────────────────────────────────────────

def _alpaca_headers():
    return {
        "APCA-API-KEY-ID":     os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }

def _alpaca_stock_quote(symbol: str) -> Optional[dict]:
    """Real-time IEX quote from Alpaca (US equities)."""
    try:
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
        r = requests.get(url, headers=_alpaca_headers(), timeout=5)
        if r.status_code != 200:
            return None
        data = r.json().get("quote", {})
        bid  = float(data.get("bp", 0) or 0)
        ask  = float(data.get("ap", 0) or 0)
        if bid > 0 and ask > 0:
            price = (bid + ask) / 2
        else:
            return None
        # Get prev close for change calculation
        prev = _alpaca_prev_close(symbol)
        change = price - prev if prev else 0
        chg_pct = (change / prev * 100) if prev else 0
        return {
            "symbol": symbol, "price": price, "prev_close": prev,
            "change": round(change, 4), "change_pct": round(chg_pct, 4),
            "source": "alpaca", "delayed": False,
        }
    except Exception:
        return None

def _alpaca_prev_close(symbol: str) -> Optional[float]:
    try:
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars/latest"
        params = {"timeframe": "1Day", "limit": 2}
        r = requests.get(url, headers=_alpaca_headers(), params=params, timeout=5)
        if r.status_code != 200:
            return None
        bars = r.json().get("bars", [])
        if len(bars) >= 2:
            return float(bars[-2]["c"])
        return None
    except Exception:
        return None

def _alpaca_stock_trade(symbol: str) -> Optional[dict]:
    """Latest trade price (faster than quote for some symbols)."""
    try:
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest"
        r = requests.get(url, headers=_alpaca_headers(), timeout=5)
        if r.status_code != 200:
            return None
        trade = r.json().get("trade", {})
        price = float(trade.get("p", 0) or 0)
        if not price:
            return None
        prev = _alpaca_prev_close(symbol)
        change = price - prev if prev else 0
        chg_pct = (change / prev * 100) if prev else 0
        return {
            "symbol": symbol, "price": price, "prev_close": prev,
            "change": round(change, 4), "change_pct": round(chg_pct, 4),
            "source": "alpaca", "delayed": False,
        }
    except Exception:
        return None

def _alpaca_crypto_quote(symbol: str) -> Optional[dict]:
    """Real-time crypto quote from Alpaca. symbol must be 'BTC/USD' format."""
    try:
        # Normalize: BTC-USD → BTC/USD, already BTC/USD → BTC/USD
        if "-USD" in symbol:
            sym_clean = symbol.replace("-USD", "/USD")
        elif "/" not in symbol:
            sym_clean = symbol + "/USD"
        else:
            sym_clean = symbol

        url = "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes"
        r = requests.get(url, headers=_alpaca_headers(), params={"symbols": sym_clean}, timeout=5)
        if r.status_code != 200:
            return None
        quotes = r.json().get("quotes", {})
        q = quotes.get(sym_clean, {})
        bid = float(q.get("bp", 0) or 0)
        ask = float(q.get("ap", 0) or 0)
        if not (bid and ask):
            return None
        price = (bid + ask) / 2
        prev = _alpaca_crypto_prev(sym_clean)
        change = price - prev if prev else 0
        chg_pct = (change / prev * 100) if prev else 0
        return {
            "symbol": symbol, "price": round(price, 2), "prev_close": prev,
            "change": round(change, 4), "change_pct": round(chg_pct, 4),
            "source": "alpaca_crypto", "delayed": False,
        }
    except Exception:
        return None

def _alpaca_crypto_prev(symbol: str) -> Optional[float]:
    """Get previous day close. Uses open of current day bar as proxy if only 1 bar."""
    try:
        url = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
        params = {"symbols": symbol, "timeframe": "1Day", "limit": 2}
        r = requests.get(url, headers=_alpaca_headers(), params=params, timeout=5)
        if r.status_code != 200:
            return None
        bars = r.json().get("bars", {}).get(symbol, [])
        if len(bars) >= 2:
            return float(bars[-2]["c"])
        elif len(bars) == 1:
            # Use today's open as proxy for prev close
            return float(bars[0]["o"])
        return None
    except Exception:
        return None


# ── Finnhub ───────────────────────────────────────────────────────────────────

def _finnhub_quote(symbol: str) -> Optional[dict]:
    """Real-time quote from Finnhub (free tier)."""
    try:
        api_key = os.getenv("FINNHUB_API_KEY", "")
        if not api_key:
            return None
        url = "https://finnhub.io/api/v1/quote"
        r = requests.get(url, params={"symbol": symbol, "token": api_key}, timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        price = float(data.get("c", 0) or 0)
        if not price:
            return None
        prev  = float(data.get("pc", 0) or price)
        change = price - prev
        chg_pct = (change / prev * 100) if prev else 0
        return {
            "symbol": symbol, "price": price, "prev_close": prev,
            "change": round(change, 4), "change_pct": round(chg_pct, 4),
            "volume": int(data.get("v", 0) or 0),
            "high": float(data.get("h", 0) or 0),
            "low":  float(data.get("l", 0) or 0),
            "open": float(data.get("o", 0) or 0),
            "source": "finnhub", "delayed": False,
        }
    except Exception:
        return None


# ── Polygon fallback ──────────────────────────────────────────────────────────

def _polygon_quote(symbol: str) -> Optional[dict]:
    """Polygon last trade (free tier = 15-min delayed)."""
    try:
        api_key = os.getenv("POLYGON_API_KEY", "")
        if not api_key:
            return None
        url = f"https://api.polygon.io/v2/last/trade/{symbol}"
        r = requests.get(url, params={"apiKey": api_key}, timeout=5)
        if r.status_code != 200:
            return None
        result = r.json().get("results", {})
        price = float(result.get("p", 0) or 0)
        if not price:
            return None
        return {
            "symbol": symbol, "price": price,
            "change": 0, "change_pct": 0,
            "source": "polygon", "delayed": True,
        }
    except Exception:
        return None


# ── Webull (unauthenticated, real-time) ───────────────────────────────────────

def _webull_quote(symbol: str) -> Optional[dict]:
    """Real-time quote from Webull (no login required)."""
    try:
        from webull import webull as Webull
        wb = Webull()
        q = wb.get_quote(symbol)
        if not q or not q.get("close"):
            return None
        price = float(q["close"])
        prev  = float(q.get("preClose", price))
        change = price - prev
        chg_pct = (change / prev * 100) if prev else 0
        return {
            "symbol": symbol, "price": price, "prev_close": prev,
            "change": round(change, 4), "change_pct": round(chg_pct, 4),
            "volume": int(q.get("volume", 0) or 0),
            "high": float(q.get("high", 0) or 0),
            "low":  float(q.get("low", 0) or 0),
            "open": float(q.get("open", 0) or 0),
            "source": "webull", "delayed": False,
        }
    except Exception:
        return None

def _webull_bars(symbol: str, interval: str = "m5", count: int = 60):
    """Real-time OHLCV bars from Webull. interval: m1/m5/m15/m30/h1/d1"""
    try:
        from webull import webull as Webull
        wb = Webull()
        df = wb.get_bars(symbol, interval=interval, count=count)
        return df if not df.empty else None
    except Exception:
        return None


# ── yfinance last resort ───────────────────────────────────────────────────────

def _yfinance_quote(symbol: str) -> Optional[dict]:
    try:
        import yfinance as yf
        tk   = yf.Ticker(symbol)
        hist = tk.history(period="2d", interval="1m")
        if hist.empty:
            return None
        price = float(hist["Close"].iloc[-1])
        prev  = float(hist["Close"].iloc[0])
        chg   = (price - prev) / prev * 100 if prev else 0
        return {
            "symbol": symbol, "price": price, "prev_close": prev,
            "change": round(price - prev, 4), "change_pct": round(chg, 4),
            "volume": int(hist["Volume"].iloc[-1]),
            "source": "yfinance", "delayed": True,
        }
    except Exception:
        return None


# ── Main public interface ─────────────────────────────────────────────────────

def get_quote(symbol: str) -> Optional[dict]:
    """
    Get best available real-time quote for any symbol.
    Returns dict with: symbol, price, change, change_pct, source, delayed
    """
    # Resolve proxy for futures/commodities
    label = symbol
    scale = None
    actual_symbol = symbol

    if symbol in PROXY_MAP:
        info   = PROXY_MAP[symbol]
        actual_symbol = info["proxy"]
        label  = info["label"]
        scale  = info.get("scale")

    # Crypto path
    is_crypto = (
        actual_symbol in CRYPTO_SYMBOLS
        or "/" in actual_symbol
        or symbol in ("BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD")
    )
    if is_crypto:
        # Normalize to BTC/USD format for Alpaca
        crypto_sym = actual_symbol.replace("-USD", "/USD")
        if "/" not in crypto_sym:
            crypto_sym = crypto_sym + "/USD"
        result = _alpaca_crypto_quote(crypto_sym)
        if result:
            result["label"] = label
            result["symbol"] = symbol
            return result
        result = _finnhub_quote(actual_symbol.replace("/", "").replace("-", ""))
        if result:
            result["label"] = label
            return result
        return _yfinance_quote(symbol)

    # Equity path: Alpaca → Finnhub → Polygon → yfinance
    result = _alpaca_stock_trade(actual_symbol)
    if not result:
        result = _alpaca_stock_quote(actual_symbol)
    if not result:
        result = _finnhub_quote(actual_symbol)
    if not result:
        result = _polygon_quote(actual_symbol)
    if not result:
        result = _webull_quote(actual_symbol)
    if not result:
        result = _yfinance_quote(actual_symbol)

    if result:
        result["label"] = label
        result["original_symbol"] = symbol
        # Apply scale for futures proxies (ETF → approximate futures price)
        if scale and result.get("price"):
            result["price_raw"] = result["price"]
            result["price"] = round(result["price"] * scale, 2)
            result["change"] = round(result["change"] * scale, 4) if result.get("change") else 0
            result["proxy_note"] = f"via {actual_symbol} × {scale}"
    return result


def get_quotes(symbols: list) -> dict:
    """Batch fetch quotes. Returns {symbol: quote_dict}."""
    return {sym: get_quote(sym) for sym in symbols}


def get_price(symbol: str) -> float:
    """Convenience: just return the price float, or 0.0 on failure."""
    q = get_quote(symbol)
    return float(q["price"]) if q and q.get("price") else 0.0


def get_change_pct(symbol: str) -> float:
    """Convenience: just return change %, or 0.0 on failure."""
    q = get_quote(symbol)
    return float(q["change_pct"]) if q and q.get("change_pct") else 0.0


if __name__ == "__main__":
    # Quick test
    test_symbols = ["NVDA", "SPY", "BTC-USD", "ES=F", "GC=F", "ETH-USD"]
    print("Testing real-time quote layer...\n")
    for sym in test_symbols:
        q = get_quote(sym)
        if q:
            delayed = "⚠️ DELAYED" if q.get("delayed") else "✅ LIVE"
            proxy = f" [{q.get('proxy_note','')}]" if q.get("proxy_note") else ""
            print(f"  {delayed} {q.get('label', sym):30s} ${q['price']:>12,.2f}  {q['change_pct']:+.2f}%  [{q['source']}]{proxy}")
        else:
            print(f"  ❌ FAILED  {sym}")
