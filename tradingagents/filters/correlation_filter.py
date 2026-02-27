"""
CooperCorp PRJ-002 — Correlation Filter
Blocks new positions in the same sector as existing open positions.
"""
from tradingagents.utils.strategy_config import get_sector
from tradingagents.brokers.alpaca import AlpacaBroker


class CorrelationFilter:
    def __init__(self, broker: AlpacaBroker):
        self.broker = broker

    def is_too_correlated(self, new_symbol: str) -> dict:
        """
        Returns {"ok": True} or {"ok": False, "reason": "...", "conflicting": "TICKER"}
        Blocks if same sector as an existing open position.
        """
        new_sector = get_sector(new_symbol)
        if new_sector is None:
            return {"ok": True}  # Unknown sector — allow

        positions = self.broker.get_positions()
        for pos in positions:
            existing_sector = get_sector(pos.symbol)
            if existing_sector == new_sector:
                return {
                    "ok": False,
                    "reason": f"{new_symbol} ({new_sector}) correlates with existing {pos.symbol} ({existing_sector})",
                    "conflicting": pos.symbol,
                }
        return {"ok": True}
