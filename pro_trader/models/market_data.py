"""Market data models — structured inputs for analyst plugins."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Quote:
    """Real-time or delayed price quote."""
    symbol: str
    price: float
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    avg_volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    prev_close: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""

    @property
    def volume_ratio(self) -> float:
        if self.avg_volume > 0:
            return self.volume / self.avg_volume
        return 1.0


@dataclass
class Technicals:
    """Technical indicators snapshot."""
    symbol: str
    rsi: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_cross: Optional[str] = None       # "bullish" | "bearish" | None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_squeeze: bool = False
    bb_position: Optional[float] = None    # 0.0 (lower band) to 1.0 (upper band)
    atr: Optional[float] = None
    vwap: Optional[float] = None
    volume_ratio: float = 1.0
    above_sma20: bool = False
    above_sma50: bool = False
    above_sma200: bool = False
    trend: str = "neutral"                 # "bullish" | "bearish" | "neutral"
    source: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class MarketData:
    """Aggregated market data for a single symbol — input to analysts."""
    ticker: str
    asset_type: str = "equity"             # equity | futures | crypto | fx
    quote: Optional[Quote] = None
    technicals: Optional[Technicals] = None
    fundamentals: dict = field(default_factory=dict)
    news: list = field(default_factory=list)
    sentiment: dict = field(default_factory=dict)
    options_flow: dict = field(default_factory=dict)
    monitor_signals: dict = field(default_factory=dict)
    contract_spec: dict = field(default_factory=dict)  # futures only
    futures_context: str = ""                           # futures only
    raw: dict = field(default_factory=dict)             # pass-through for plugins
    score: float = 0.0                                  # pre-score from data phase

    @property
    def price(self) -> float:
        if self.quote:
            return self.quote.price
        return 0.0

    def to_dict(self) -> dict:
        d = {
            "ticker": self.ticker,
            "asset_type": self.asset_type,
            "price": self.price,
            "score": self.score,
        }
        if self.quote:
            d["quote"] = self.quote.__dict__
        if self.technicals:
            d["technicals"] = self.technicals.to_dict()
        if self.contract_spec:
            d["contract_spec"] = self.contract_spec
        if self.futures_context:
            d["futures_context"] = self.futures_context
        return d
