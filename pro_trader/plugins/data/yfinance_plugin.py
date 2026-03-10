"""YFinance data plugin — wraps existing tradingagents yfinance integration."""

from __future__ import annotations
import logging
from typing import Optional

from pro_trader.core.interfaces import DataPlugin
from pro_trader.models.market_data import MarketData, Quote, Technicals

logger = logging.getLogger(__name__)


class YFinancePlugin(DataPlugin):
    name = "yfinance"
    version = "1.0.0"
    description = "Market data via Yahoo Finance (free, no API key)"
    provides = ["quotes", "technicals", "fundamentals", "news"]

    def __init__(self):
        self._yf = None

    def startup(self) -> None:
        try:
            import yfinance
            self._yf = yfinance
        except ImportError:
            logger.warning("yfinance not installed — plugin disabled")
            self.enabled = False

    def supports(self, symbol: str) -> bool:
        # yfinance doesn't support futures symbols like /METH26
        return not symbol.startswith("/")

    def get_quote(self, symbol: str) -> Optional[Quote]:
        if not self._yf:
            return None
        try:
            ticker = self._yf.Ticker(symbol)
            info = ticker.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            prev = info.get("previousClose", price)
            change = price - prev if price and prev else 0
            change_pct = (change / prev * 100) if prev else 0

            return Quote(
                symbol=symbol,
                price=price or 0.0,
                change=change,
                change_pct=round(change_pct, 2),
                volume=info.get("volume", 0),
                avg_volume=info.get("averageVolume", 0),
                bid=info.get("bid", 0),
                ask=info.get("ask", 0),
                high=info.get("dayHigh", 0),
                low=info.get("dayLow", 0),
                open=info.get("open", 0),
                prev_close=prev or 0,
                source="yfinance",
            )
        except Exception as e:
            logger.warning(f"YFinance quote failed for {symbol}: {e}")
            return None

    def get_technicals(self, symbol: str, period: str = "3mo") -> Optional[Technicals]:
        if not self._yf:
            return None
        try:
            ticker = self._yf.Ticker(symbol)
            hist = ticker.history(period=period)
            if hist.empty:
                return None

            close = hist["Close"]
            price = close.iloc[-1]

            # Calculate indicators
            sma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else None
            sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
            ema9 = close.ewm(span=9).mean().iloc[-1] if len(close) >= 9 else None
            ema21 = close.ewm(span=21).mean().iloc[-1] if len(close) >= 21 else None

            # RSI
            rsi = self._calc_rsi(close)

            # MACD
            macd, signal_line, macd_hist, macd_cross = self._calc_macd(close)

            # Bollinger Bands
            bb_mid = sma20
            bb_std = close.rolling(20).std().iloc[-1] if len(close) >= 20 else None
            bb_upper = bb_mid + 2 * bb_std if bb_mid and bb_std else None
            bb_lower = bb_mid - 2 * bb_std if bb_mid and bb_std else None
            bb_squeeze = bb_std < close.rolling(20).std().mean() if bb_std else False
            bb_position = None
            if bb_upper and bb_lower and bb_upper != bb_lower:
                bb_position = (price - bb_lower) / (bb_upper - bb_lower)

            # Volume ratio
            vol = hist["Volume"]
            avg_vol = vol.rolling(20).mean().iloc[-1] if len(vol) >= 20 else vol.mean()
            vol_ratio = vol.iloc[-1] / avg_vol if avg_vol > 0 else 1.0

            return Technicals(
                symbol=symbol,
                rsi=rsi,
                sma_20=sma20,
                sma_50=sma50,
                ema_9=ema9,
                ema_21=ema21,
                macd=macd,
                macd_signal=signal_line,
                macd_histogram=macd_hist,
                macd_cross=macd_cross,
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_middle=bb_mid,
                bb_squeeze=bb_squeeze,
                bb_position=bb_position,
                volume_ratio=round(vol_ratio, 2),
                above_sma20=price > sma20 if sma20 else False,
                above_sma50=price > sma50 if sma50 else False,
                source="yfinance",
            )
        except Exception as e:
            logger.warning(f"YFinance technicals failed for {symbol}: {e}")
            return None

    def get_fundamentals(self, symbol: str) -> dict:
        if not self._yf:
            return {}
        try:
            ticker = self._yf.Ticker(symbol)
            info = ticker.info or {}
            return {
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "revenue": info.get("totalRevenue"),
                "profit_margin": info.get("profitMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }
        except Exception:
            return {}

    def get_news(self, symbol: str, limit: int = 10) -> list[dict]:
        if not self._yf:
            return []
        try:
            ticker = self._yf.Ticker(symbol)
            news = ticker.news or []
            return [
                {"title": n.get("title", ""), "url": n.get("link", ""),
                 "source": n.get("publisher", ""), "published": n.get("providerPublishTime")}
                for n in news[:limit]
            ]
        except Exception:
            return []

    @staticmethod
    def _calc_rsi(close, period: int = 14) -> Optional[float]:
        if len(close) < period + 1:
            return None
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean().iloc[-1]
        if loss == 0:
            return 100.0
        rs = gain / loss
        return round(100 - (100 / (1 + rs)), 1)

    @staticmethod
    def _calc_macd(close):
        if len(close) < 26:
            return None, None, None, None
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        hist = macd - signal
        cross = None
        if len(hist) >= 2:
            if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
                cross = "bullish"
            elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
                cross = "bearish"
        return macd.iloc[-1], signal.iloc[-1], hist.iloc[-1], cross

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": "ok" if self._yf else "unavailable",
        }
