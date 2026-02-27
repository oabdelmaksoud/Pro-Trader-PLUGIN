"""
CooperCorp PRJ-002 — Trade Executor
Parses BUY/SELL/HOLD from agent final_trade_decision and routes to AlpacaBroker.
"""
import re
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tradingagents.brokers.alpaca import AlpacaBroker

logger = logging.getLogger(__name__)
LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "executions.jsonl"


class TradeExecutor:
    def __init__(self, broker: Optional[AlpacaBroker] = None, portfolio_pct: float = 0.05):
        self.broker = broker or AlpacaBroker()
        self.portfolio_pct = portfolio_pct  # fraction of buying power per trade

    def parse_decision(self, text: str, symbol: str) -> dict:
        """Extract BUY/SELL/HOLD action from agent output text."""
        match = re.search(r'\b(BUY|SELL|HOLD)\b', text.upper())
        action = match.group(1) if match else "HOLD"
        return {
            "action": action,
            "symbol": symbol.upper(),
            "reasoning": text[:500],
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }

    def calculate_qty(self, symbol: str) -> float:
        """Size position as portfolio_pct of buying power / current price."""
        buying_power = self.broker.get_buying_power()
        budget = buying_power * self.portfolio_pct
        bar = self.broker.get_latest_bar(symbol)
        if bar is None:
            raise ValueError(f"No price data for {symbol}")
        price = float(bar["close"])
        qty = max(1, int(budget / price))
        logger.info(f"Sizing: budget=${budget:.2f}, price=${price:.2f}, qty={qty}")
        return qty

    def execute(self, decision: dict, dry_run: bool = False) -> Optional[dict]:
        """Execute the trade decision. Returns order dict or None for HOLD/dry-run."""
        action = decision["action"]
        symbol = decision["symbol"]

        if action == "HOLD":
            logger.info(f"HOLD on {symbol} — no order placed")
            self._log(decision, order=None, dry_run=dry_run)
            return None

        qty = self.calculate_qty(symbol)
        side = "buy" if action == "BUY" else "sell"

        if dry_run:
            result = {"dry_run": True, "symbol": symbol, "side": side, "qty": qty}
            logger.info(f"DRY RUN: would {side} {qty} {symbol}")
            self._log(decision, order=result, dry_run=True)
            return result

        order = self.broker.submit_order(symbol, qty, side)
        result = {
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "qty": order.qty,
            "status": order.status,
            "submitted_at": str(order.submitted_at),
        }
        logger.info(f"ORDER PLACED: {result}")
        self._log(decision, order=result, dry_run=False)
        return result

    def _log(self, decision: dict, order: Optional[dict], dry_run: bool):
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "order": order,
            "dry_run": dry_run,
        }
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
