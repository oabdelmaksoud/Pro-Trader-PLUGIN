"""
CooperCorp PRJ-002 — Relative Strength Rank
Is the ticker outperforming its sector ETF?
RS > 1.0 = outperforming (bullish confirmation)
RS < 1.0 = underperforming (headwind signal)
"""
import yfinance as yf

SECTOR_ETF = {
    "NVDA": "SMH", "AMD": "SMH", "INTC": "SMH", "AVGO": "SMH",
    "QCOM": "SMH", "AMAT": "SMH", "LRCX": "SMH", "KLAC": "SMH",
    "ARM": "SMH", "SMCI": "SMH", "MRVL": "SMH",
    "MSFT": "XLK", "AAPL": "XLK", "GOOGL": "XLK", "META": "XLK",
    "AMZN": "XLK", "CRM": "XLK", "NOW": "XLK", "SNOW": "XLK",
    "TSLA": "XLK", "PLTR": "XLK", "CRWD": "XLK", "NET": "XLK",
    "COIN": "XLF", "HOOD": "XLF", "JPM": "XLF", "GS": "XLF", "BAC": "XLF",
    "MRNA": "XBI", "BIIB": "XBI", "VRTX": "XBI", "LLY": "XBI",
    "MSTR": "QQQ",
}


def get_relative_strength(symbol: str, period_days: int = 10) -> dict:
    """
    Relative strength vs sector ETF over N days.
    RS = (ticker_return / etf_return). RS > 1.0 = outperforming.
    """
    try:
        etf = SECTOR_ETF.get(symbol.upper(), "QQQ")

        def pct_change(sym, days):
            hist = yf.Ticker(sym).history(period=f"{days + 5}d", interval="1d")
            if len(hist) < 2:
                return 0.0
            recent = hist["Close"].tail(days + 1)
            return (float(recent.iloc[-1]) - float(recent.iloc[0])) / float(recent.iloc[0]) * 100

        ticker_return_5 = pct_change(symbol, 5)
        ticker_return_10 = pct_change(symbol, 10)
        etf_return_5 = pct_change(etf, 5)
        etf_return_10 = pct_change(etf, 10)

        rs_5 = (1 + ticker_return_5 / 100) / (1 + etf_return_5 / 100) if etf_return_5 != -100 else 0
        rs_10 = (1 + ticker_return_10 / 100) / (1 + etf_return_10 / 100) if etf_return_10 != -100 else 0

        rs_score = (rs_5 + rs_10) / 2
        outperforming = rs_score > 1.01

        if rs_score > 1.05:
            note = f"✅ Strong outperformer vs {etf} (+{(rs_score-1)*100:.1f}%)"
        elif rs_score > 1.01:
            note = f"🟡 Slight outperformer vs {etf} (+{(rs_score-1)*100:.1f}%)"
        elif rs_score > 0.97:
            note = f"⚪ In-line with {etf}"
        else:
            note = f"🔴 Underperforming {etf} ({(rs_score-1)*100:.1f}%)"

        return {
            "symbol": symbol,
            "benchmark_etf": etf,
            "ticker_return_5d": round(ticker_return_5, 2),
            "etf_return_5d": round(etf_return_5, 2),
            "ticker_return_10d": round(ticker_return_10, 2),
            "etf_return_10d": round(etf_return_10, 2),
            "rs_ratio": round(rs_score, 3),
            "outperforming": outperforming,
            "note": note,
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}
