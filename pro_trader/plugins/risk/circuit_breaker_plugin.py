"""Circuit Breaker risk plugin — halts trading on drawdown/daily loss limits.

Respects trader_profile from config for dynamic risk limits.
"""

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
    version = "1.1.0"
    description = "Halts trading when portfolio drawdown exceeds threshold"

    def __init__(self):
        self._max_drawdown_pct = 5.0
        self._max_daily_loss = 3.0
        self._max_positions = 3
        self._state_file = Path("logs/drawdown_state.json")
        self._trader_profile: dict = {}

    def configure(self, config: dict) -> None:
        self._max_drawdown_pct = config.get("max_drawdown_pct", 5.0)
        self._max_daily_loss = config.get("max_daily_loss", 3.0)
        self._max_positions = config.get("max_positions", 3)
        self._trader_profile = config.get("trader_profile", {})

        # Override from trader profile if present
        if self._trader_profile:
            profile_dd = self._trader_profile.get("max_drawdown_pct")
            if profile_dd is not None:
                self._max_drawdown_pct = float(profile_dd)
            profile_daily = self._trader_profile.get("max_daily_loss_pct")
            if profile_daily is not None:
                self._max_daily_loss = float(profile_daily)

    def evaluate(self, signal: Signal, portfolio: Portfolio) -> dict:
        warnings = []
        adjustments = {}

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
        if portfolio.position_count >= self._max_positions:
            warnings.append(f"Max positions reached: {portfolio.position_count}")

        # Recovery mode: tighten limits further as losses approach threshold
        if self._trader_profile.get("recovery_mode"):
            risk_tol = self._trader_profile.get("risk_tolerance", "moderate")
            if risk_tol == "conservative":
                # Reduce position size by 30% in conservative recovery
                adjustments["position_size_factor"] = 0.7
                warnings.append("Recovery mode (conservative): position size reduced 30%")
            elif risk_tol == "aggressive":
                # Allow full sizing but warn
                warnings.append("Recovery mode (aggressive): full sizing allowed, monitor closely")

        return {
            "approved": True,
            "reason": "passed",
            "adjustments": adjustments,
            "warnings": warnings,
        }

    def get_state(self) -> dict:
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text())
            except Exception:
                pass
        return {"halted": False}
