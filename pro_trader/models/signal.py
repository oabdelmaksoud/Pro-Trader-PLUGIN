"""Signal model — the universal output of the analysis pipeline."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    PASS = "PASS"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Signal:
    """Structured trade signal — produced by StrategyPlugin, consumed by BrokerPlugin."""
    ticker: str
    direction: Direction
    score: float                        # 0–10 composite score
    confidence: int = 5                 # 1–10 conviction
    price: float = 0.0                  # current/entry price
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward: Optional[float] = None
    position_size: float = 0.0          # dollar amount or contracts
    source: str = "pipeline"            # which plugin/pipeline produced it
    asset_type: str = "equity"          # equity | futures | crypto | fx
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    analyst_reports: dict = field(default_factory=dict)  # flash, macro, pulse
    debate_summary: str = ""
    intelligence_bonuses: list = field(default_factory=list)

    @property
    def meets_threshold(self) -> bool:
        return self.score >= 7.0 and self.confidence >= 7

    @property
    def is_actionable(self) -> bool:
        return self.direction in (Direction.BUY, Direction.SELL) and self.meets_threshold

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "direction": self.direction.value,
            "score": round(self.score, 2),
            "confidence": self.confidence,
            "price": self.price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "position_size": self.position_size,
            "source": self.source,
            "asset_type": self.asset_type,
            "timestamp": self.timestamp.isoformat(),
            "meets_threshold": self.meets_threshold,
            "metadata": self.metadata,
        }
