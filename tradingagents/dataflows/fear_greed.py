"""
CooperCorp PRJ-002 — CNN Fear & Greed Index + VIX + market sentiment.
No API key needed.
"""
import requests
import yfinance as yf


def get_fear_greed() -> dict:
    """Fetch CNN Fear & Greed Index via Alternative.me API (crypto+stock proxy)."""
    try:
        # Alternative.me provides F&G for crypto but it correlates well with stock sentiment
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        data = r.json()
        value = int(data["data"][0]["value"])
        label = data["data"][0]["value_classification"]
        return {
            "score": value,
            "label": label,  # Extreme Fear / Fear / Neutral / Greed / Extreme Greed
            "sentiment": "bearish" if value < 40 else ("bullish" if value > 60 else "neutral"),
            "source": "alternative.me",
        }
    except Exception as e:
        return {"error": str(e)}


def get_vix() -> dict:
    """Get current VIX (CBOE Volatility Index)."""
    try:
        tk = yf.Ticker("^VIX")
        hist = tk.history(period="5d", interval="1d")
        if hist.empty:
            return {"error": "No VIX data"}
        vix = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else vix
        return {
            "vix": round(vix, 2),
            "prev_vix": round(prev, 2),
            "change": round(vix - prev, 2),
            "regime": "high_volatility" if vix > 30 else ("elevated" if vix > 20 else "low_volatility"),
            "position_multiplier": 0.4 if vix > 30 else (0.7 if vix > 20 else 1.0),
        }
    except Exception as e:
        return {"error": str(e)}


def get_put_call_ratio() -> dict:
    """Get CBOE equity put/call ratio from yfinance."""
    try:
        # Use SPY as proxy for overall market PCR
        tk = yf.Ticker("SPY")
        opts = tk.options
        if not opts:
            return {"error": "No options data"}
        exp = opts[0]  # nearest expiry
        chain = tk.option_chain(exp)
        total_calls = chain.calls["volume"].sum()
        total_puts = chain.puts["volume"].sum()
        pcr = float(total_puts / total_calls) if total_calls > 0 else 1.0
        return {
            "pcr": round(pcr, 3),
            "sentiment": "bearish" if pcr > 1.2 else ("bullish" if pcr < 0.7 else "neutral"),
            "total_calls": int(total_calls),
            "total_puts": int(total_puts),
            "expiry": exp,
        }
    except Exception as e:
        return {"error": str(e)}


def get_market_sentiment_summary() -> dict:
    """Combined market sentiment: F&G + VIX + PCR."""
    fg = get_fear_greed()
    vix = get_vix()
    pcr = get_put_call_ratio()

    # Aggregate signal
    signals = []
    if "score" in fg:
        signals.append(fg["sentiment"])
    if "regime" in vix:
        signals.append("bearish" if vix["regime"] == "high_volatility" else "neutral")
    if "sentiment" in pcr:
        signals.append(pcr["sentiment"])

    bearish = signals.count("bearish")
    bullish = signals.count("bullish")
    overall = "bearish" if bearish > bullish else ("bullish" if bullish > bearish else "neutral")

    return {
        "overall": overall,
        "fear_greed": fg,
        "vix": vix,
        "put_call_ratio": pcr,
    }
