"""Circuit Breaker risk plugin — wraps tradingagents/risk/circuit_breaker.py."""

from __future__ import annotations
import json
import logging
from pathlib import Path

from pro_trader.core.interfaces import RiskPlugin
from pro_trader.models.signal import Signal
from pro_trader.models.position import Portfolio

logger = logging.getLogger(__name__)


class CircuitBreakerPlugin(RiskPlugin):
    name = "circuit_breaker"
    version = "1.0.0"
    description = "Halts trading when portfolio drawdown exceeds threshold"

    def __init__(self):
        self._max_drawdown_pct = 5.0
        self._max_daily_loss = 3.0
        self._state_file = Path("logs/drawdown_state.json")

    def configure(self, config: dict) -> None:
        self._max_drawdown_pct = config.get("max_drawdown_pct", 5.0)
        self._max_daily_loss = config.get("max_daily_loss", 3.0)

    def evaluate(self, signal: Signal, portfolio: Portfolio) -> dict:
        warnings = []

        # Check drawdown state file
        if self._state_file.exists():
            try:
                state = json.loads(self._state_file.read_text())
                if state.get("halted"):
                    dd = state.get("drawdown_pct", "?")
                    return {
                        "approved": False,
                        "reason": f"Drawdown halt active — portfolio down {dd}%",
                        "adjustments": {},
                        "warnings": [f"Circuit breaker triggered at {dd}% drawdown"],
                    }
            except Exception as e:
                logger.warning(f"Failed to read drawdown state: {e}")

        # Check daily P&L
        if portfolio.today_pnl < 0:
            daily_loss_pct = abs(portfolio.today_pnl) / portfolio.equity * 100 if portfolio.equity > 0 else 0
            if daily_loss_pct >= self._max_daily_loss:
                return {
                    "approved": False,
                    "reason": f"Daily loss {daily_loss_pct:.1f}% exceeds {self._max_daily_loss}% limit",
                    "adjustments": {},
                    "warnings": [f"Daily loss limit hit: {daily_loss_pct:.1f}%"],
                }
            elif daily_loss_pct >= self._max_daily_loss * 0.7:
                warnings.append(f"Daily loss approaching limit: {daily_loss_pct:.1f}%")

        # Check position count
        if portfolio.position_count >= 3:
            warnings.append(f"Max positions reached: {portfolio.position_count}")

        return {
            "approved": True,
            "reason": "passed",
            "adjustments": {},
            "warnings": warnings,
        }

    def get_state(self) -> dict:
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text())
            except Exception:
                pass
        return {"halted": False}
