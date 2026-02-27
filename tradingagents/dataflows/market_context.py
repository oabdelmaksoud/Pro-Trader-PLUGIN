"""
CooperCorp PRJ-002 — Market context signals.
Sector ETF momentum, Bitcoin correlation, pre-market gaps.
No API key needed — uses yfinance.
"""
import yfinance as yf
from datetime import datetime, timedelta
import pytz


# Sector ETF map
SECTOR_ETFS = {
    "tech": "XLK",
    "semis": "SMH",
    "nasdaq": "QQQ",
    "sp500": "SPY",
    "financials": "XLF",
    "energy": "XLE",
    "biotech": "XBI",
    "growth": "ARKK",
    "leveraged_tech": "TQQQ",
    "leveraged_semis": "SOXL",
}

# Ticker → sector mapping for context
TICKER_SECTOR = {
    "NVDA": "semis", "AMD": "semis", "INTC": "semis", "AVGO": "semis",
    "QCOM": "semis", "AMAT": "semis", "LRCX": "semis", "KLAC": "semis",
    "MSFT": "tech", "AAPL": "tech", "GOOGL": "tech", "META": "tech",
    "AMZN": "tech", "CRM": "tech", "NOW": "tech", "SNOW": "tech",
    "TSLA": "tech", "PLTR": "tech", "CRWD": "tech", "NET": "tech",
    "COIN": "financials", "HOOD": "financials", "JPM": "financials",
    "GS": "financials", "BAC": "financials",
    "MRNA": "biotech", "BIIB": "biotech", "VRTX": "biotech", "LLY": "biotech",
    "MSTR": "tech", "ARM": "semis", "SMCI": "semis",
}


def get_sector_momentum(ticker: str = None) -> dict:
    """Get sector ETF performance today. If ticker provided, return relevant sector first."""
    try:
        # Pick relevant ETFs
        etfs_to_check = ["SPY", "QQQ", "SMH", "XLK", "XLF"]
        if ticker and ticker.upper() in TICKER_SECTOR:
            sector = TICKER_SECTOR[ticker.upper()]
            relevant_etf = SECTOR_ETFS.get(sector)
            if relevant_etf and relevant_etf not in etfs_to_check:
                etfs_to_check.insert(0, relevant_etf)

        result = {}
        for etf in etfs_to_check:
            try:
                tk = yf.Ticker(etf)
                hist = tk.history(period="2d", interval="1d")
                if len(hist) >= 2:
                    today = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2])
                    chg = (today - prev) / prev * 100
                    result[etf] = {
                        "price": round(today, 2),
                        "change_pct": round(chg, 2),
                        "trend": "bullish" if chg > 0.5 else ("bearish" if chg < -0.5 else "neutral"),
                    }
            except Exception:
                pass

        # Sector headwind assessment
        if ticker and ticker.upper() in TICKER_SECTOR:
            sector = TICKER_SECTOR[ticker.upper()]
            relevant_etf = SECTOR_ETFS.get(sector, "QQQ")
            if relevant_etf in result:
                sector_chg = result[relevant_etf]["change_pct"]
                result["sector_assessment"] = {
                    "ticker": ticker,
                    "sector": sector,
                    "etf": relevant_etf,
                    "headwind": sector_chg < -1.0,
                    "tailwind": sector_chg > 0.5,
                    "note": f"{relevant_etf} {'headwind' if sector_chg < -1.0 else 'tailwind' if sector_chg > 0.5 else 'neutral'}: {sector_chg:+.2f}%",
                }

        return result
    except Exception as e:
        return {"error": str(e)}


def get_btc_signal() -> dict:
    """BTC momentum — leads tech by 30-60 min. Critical for MSTR, COIN, and high-beta tech."""
    try:
        tk = yf.Ticker("BTC-USD")
        hist = tk.history(period="2d", interval="1h")
        if hist.empty:
            return {"error": "No BTC data"}
        price = float(hist["Close"].iloc[-1])
        price_1h = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
        price_4h = float(hist["Close"].iloc[-5]) if len(hist) > 4 else price
        change_1h = (price - price_1h) / price_1h * 100
        change_4h = (price - price_4h) / price_4h * 100
        signal = "bullish" if change_1h > 1 else ("bearish" if change_1h < -1 else "neutral")
        return {
            "price": round(price, 0),
            "change_1h": round(change_1h, 2),
            "change_4h": round(change_4h, 2),
            "signal": signal,
            "note": f"BTC {signal}: {change_1h:+.2f}% (1h), {change_4h:+.2f}% (4h). {'⚠️ Strong headwind for crypto-correlated stocks' if change_1h < -2 else '✅ Tailwind for MSTR/COIN' if change_1h > 2 else 'Neutral'}",
        }
    except Exception as e:
        return {"error": str(e)}


def get_premarket_gaps(min_gap_pct: float = 2.0) -> list:
    """Detect pre-market gaps with quality scoring."""
    try:
        # Check top tickers for pre-market moves
        tickers = ["NVDA", "MSFT", "AMD", "TSLA", "AAPL", "META", "GOOGL",
                   "AMZN", "PLTR", "CRWD", "ARM", "MSTR", "COIN"]
        gaps = []
        for sym in tickers:
            try:
                tk = yf.Ticker(sym)
                hist_pre = tk.history(period="2d", interval="5m")
                hist_day = tk.history(period="2d", interval="1d")
                if hist_pre.empty or hist_day.empty:
                    continue
                prev_close = float(hist_day["Close"].iloc[-2]) if len(hist_day) >= 2 else None
                current = float(hist_pre["Close"].iloc[-1])
                if not prev_close:
                    continue
                gap_pct = (current - prev_close) / prev_close * 100
                if abs(gap_pct) >= min_gap_pct:
                    vol_ratio = float(hist_pre["Volume"].iloc[-1]) / (float(hist_pre["Volume"].mean()) + 1)
                    gaps.append({
                        "symbol": sym,
                        "gap_pct": round(gap_pct, 2),
                        "direction": "up" if gap_pct > 0 else "down",
                        "volume_ratio": round(vol_ratio, 2),
                        "quality": "high" if vol_ratio > 2 else ("medium" if vol_ratio > 1 else "low"),
                        "tradeable": gap_pct > 0 and vol_ratio > 1.5,
                    })
            except Exception:
                pass
        return sorted(gaps, key=lambda x: abs(x["gap_pct"]), reverse=True)
    except Exception as e:
        return [{"error": str(e)}]


def get_full_market_context(ticker: str = None) -> dict:
    """All market context signals in one call."""
    return {
        "sector_momentum": get_sector_momentum(ticker),
        "btc_signal": get_btc_signal(),
        "premarket_gaps": get_premarket_gaps(),
    }
