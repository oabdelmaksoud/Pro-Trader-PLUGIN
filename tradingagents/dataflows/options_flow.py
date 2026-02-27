"""
Real options flow screening via yfinance options chain.
Detects unusual activity: volume > 3x open interest, or volume > daily avg.
"""
import yfinance as yf
from datetime import date


class OptionsFlowScreener:
    def get_unusual_activity(self, symbol: str) -> dict:
        """
        Scans near-term options chain for unusual call/put activity.
        Returns summary dict with unusual_calls, unusual_puts, put_call_ratio, sentiment.
        """
        try:
            t = yf.Ticker(symbol)
            exps = t.options
            if not exps:
                return {"symbol": symbol, "error": "no options data"}

            # Use nearest expiration
            nearest_exp = exps[0]
            chain = t.option_chain(nearest_exp)
            calls = chain.calls
            puts = chain.puts

            # Unusual = volume > 3x openInterest OR volume > 500
            unusual_calls = calls[
                (calls["volume"] > calls["openInterest"] * 3) |
                (calls["volume"] > 500)
            ][["strike", "volume", "openInterest", "impliedVolatility"]].head(5)

            unusual_puts = puts[
                (puts["volume"] > puts["openInterest"] * 3) |
                (puts["volume"] > 500)
            ][["strike", "volume", "openInterest", "impliedVolatility"]].head(5)

            total_call_vol = calls["volume"].sum()
            total_put_vol = puts["volume"].sum()
            pcr = round(total_put_vol / total_call_vol, 2) if total_call_vol > 0 else 1.0

            sentiment = "bullish" if pcr < 0.7 else "bearish" if pcr > 1.3 else "neutral"

            return {
                "symbol": symbol,
                "expiration": nearest_exp,
                "put_call_ratio": pcr,
                "sentiment": sentiment,
                "total_call_volume": int(total_call_vol),
                "total_put_volume": int(total_put_vol),
                "unusual_calls": unusual_calls.to_dict("records"),
                "unusual_puts": unusual_puts.to_dict("records"),
                "has_unusual_activity": len(unusual_calls) > 0 or len(unusual_puts) > 0,
            }
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}

    def screen_watchlist(self, symbols: list) -> list:
        """Returns symbols with unusual options activity, sorted by activity level."""
        results = []
        for sym in symbols:
            data = self.get_unusual_activity(sym)
            if data.get("has_unusual_activity"):
                results.append(data)
        return sorted(results, key=lambda x: x.get("total_call_volume", 0), reverse=True)
