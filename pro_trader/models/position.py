"""Position and order models."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    BRACKET = "bracket"


@dataclass
class Order:
    """Trade order to submit to a broker plugin."""
    symbol: str
    side: OrderSide
    qty: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit: Optional[float] = None
    time_in_force: str = "day"
    signal_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class OrderResult:
    """Result from broker after order submission."""
    success: bool
    order_id: str = ""
    filled_price: float = 0.0
    filled_qty: float = 0.0
    status: str = ""                    # filled | partial | rejected | error
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw: dict = field(default_factory=dict)


@dataclass
class Position:
    """Active position in the portfolio."""
    symbol: str
    qty: float
    avg_entry: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    market_value: float = 0.0
    side: str = "long"
    asset_type: str = "equity"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[datetime] = None
    signal_id: Optional[str] = None
    tags: list = field(default_factory=list)

    @property
    def pnl_pct(self) -> float:
        if self.avg_entry > 0:
            return ((self.current_price - self.avg_entry) / self.avg_entry) * 100
        return 0.0


@dataclass
class Portfolio:
    """Snapshot of the full portfolio."""
    positions: list[Position] = field(default_factory=list)
    cash: float = 0.0
    equity: float = 0.0
    buying_power: float = 0.0
    today_pnl: float = 0.0
    total_pnl: float = 0.0
    heat: float = 0.0                   # % of equity at risk
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def get_position(self, symbol: str) -> Optional[Position]:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None
