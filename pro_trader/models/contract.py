"""Futures contract model."""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    EQUITY = "equity"
    INDEX = "index"
    COMMODITY = "commodity"
    FX = "fx"
    CRYPTO = "crypto"


@dataclass
class FuturesContract:
    """Specification for a futures contract."""
    root: str                           # MET, M6E, MES, etc.
    name: str                           # Micro Ether Futures
    asset_class: AssetClass
    exchange: str = "CME"
    margin: float = 0.0
    point_value: float = 1.0
    tick_size: float = 0.01
    tick_value: float = 0.01
    contract_size: float = 1.0
    currency: str = "USD"
    session_hours: str = ""
    yfinance_proxy: str = ""            # ETH-USD, SPY, etc.
    proxy_scale: Optional[float] = None

    @property
    def is_micro(self) -> bool:
        return "micro" in self.name.lower() or self.root.startswith("M")

    def margin_headroom(self, account_value: float) -> float:
        """Percentage of account NOT used by margin."""
        if account_value <= 0:
            return 0.0
        return max(0.0, (1 - self.margin / account_value) * 100)

    def risk_per_trade(self, stop_ticks: int) -> float:
        """Dollar risk for a given stop distance in ticks."""
        return stop_ticks * self.tick_value

    def max_contracts(self, account_value: float, risk_pct: float = 0.02,
                      stop_ticks: int = 20) -> int:
        """Max contracts within risk limit."""
        risk_budget = account_value * risk_pct
        risk_per = self.risk_per_trade(stop_ticks)
        if risk_per <= 0:
            return 0
        return max(0, int(risk_budget / risk_per))

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "name": self.name,
            "asset_class": self.asset_class.value,
            "exchange": self.exchange,
            "margin": self.margin,
            "point_value": self.point_value,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "contract_size": self.contract_size,
        }
