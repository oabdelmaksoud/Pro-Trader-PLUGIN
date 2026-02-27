"""
CooperCorp PRJ-002 — Daily Circuit Breaker
Pauses trading if portfolio drawdown exceeds max_daily_loss_pct.
"""
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
STATE_FILE = Path(__file__).parent.parent.parent / "logs" / "circuit_breaker.json"


class CircuitBreaker:
    def __init__(self, broker, max_daily_loss_pct: float = 0.05):
        self.broker = broker
        self.max_daily_loss_pct = max_daily_loss_pct

    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save_state(self, state: dict):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))

    def reset(self):
        """Record start-of-day portfolio value. Call at ~9:25 AM each trading day."""
        from tradingagents.utils.market_hours import is_market_holiday
        today = date.today()
        if is_market_holiday(today):
            logger.info("CircuitBreaker.reset() skipped — market holiday")
            return
        value = self.broker.get_portfolio_value()
        state = {
            "date": today.isoformat(),
            "start_value": value,
            "tripped": False,
        }
        self._save_state(state)
        logger.info(f"CircuitBreaker reset: start_value=${value:,.2f} for {today}")

    def check(self) -> dict:
        """Returns {"ok": True} or {"ok": False, "reason": "..."}"""
        state = self._load_state()
        today = date.today().isoformat()

        if state.get("tripped") and state.get("date") == today:
            return {"ok": False, "reason": "Circuit breaker already tripped today"}

        if state.get("date") != today or "start_value" not in state:
            logger.warning("CircuitBreaker: no start-of-day value recorded — allowing trade")
            return {"ok": True}

        start_value = float(state["start_value"])
        if start_value <= 0:
            logger.warning("CircuitBreaker: start_value is 0 — allowing trade (run reset() first)")
            return {"ok": True}
        current_value = self.broker.get_portfolio_value()
        drawdown = (start_value - current_value) / start_value

        if drawdown >= self.max_daily_loss_pct:
            state["tripped"] = True
            self._save_state(state)
            reason = (
                f"Daily loss limit hit: drawdown={drawdown:.2%} >= "
                f"max={self.max_daily_loss_pct:.2%} "
                f"(start=${start_value:,.2f}, now=${current_value:,.2f})"
            )
            logger.error(f"🚨 CIRCUIT BREAKER TRIPPED: {reason}")
            return {"ok": False, "reason": reason}

        logger.info(f"CircuitBreaker ok: drawdown={drawdown:.2%}")
        return {"ok": True}

    def is_tripped(self) -> bool:
        state = self._load_state()
        return state.get("tripped", False) and state.get("date") == date.today().isoformat()
