"""
CooperCorp PRJ-002 — Trade Ledger
Tracks closed trades and computes P&L metrics.
"""
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
LEDGER_PATH = Path(__file__).parent.parent.parent / "logs" / "ledger.jsonl"


class TradeLedger:
    def record_close(
        self,
        ticker: str,
        side: str,
        entry_price: float,
        exit_price: float,
        qty: float,
        hold_minutes: float = 0,
        reason: str = "",
    ):
        """Record a closed trade to the ledger."""
        if side in ("buy", "long"):
            pnl_dollar = (exit_price - entry_price) * qty
        else:  # short / sell
            pnl_dollar = (entry_price - exit_price) * qty

        pnl_pct = pnl_dollar / (entry_price * qty) if entry_price else 0.0

        entry = {
            "date": date.today().isoformat(),
            "ticker": ticker.upper(),
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "qty": qty,
            "pnl_dollar": round(pnl_dollar, 2),
            "pnl_pct": round(pnl_pct, 4),
            "hold_minutes": hold_minutes,
            "reason": reason,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(f"Ledger: {ticker} {side} P&L=${pnl_dollar:+.2f} ({pnl_pct:+.2%})")
        return entry

    def _load_trades(self, days: Optional[int] = None) -> list:
        if not LEDGER_PATH.exists():
            return []
        trades = []
        cutoff = None
        if days is not None:
            from datetime import timedelta
            cutoff = (date.today() - timedelta(days=days)).isoformat()
        with open(LEDGER_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                    if cutoff is None or t.get("date", "") >= cutoff:
                        trades.append(t)
                except Exception:
                    pass
        return trades

    def summary(self, days: Optional[int] = None) -> dict:
        trades = self._load_trades(days)
        if not trades:
            return {
                "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "total_pnl": 0.0,
                "profit_factor": 0.0, "best_trade": None, "worst_trade": None,
            }

        wins = [t for t in trades if t["pnl_dollar"] > 0]
        losses = [t for t in trades if t["pnl_dollar"] <= 0]
        total_pnl = sum(t["pnl_dollar"] for t in trades)
        gross_profit = sum(t["pnl_dollar"] for t in wins)
        gross_loss = abs(sum(t["pnl_dollar"] for t in losses))

        sorted_by_pnl = sorted(trades, key=lambda t: t["pnl_dollar"])
        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
            "avg_win_pct": round(sum(t["pnl_pct"] for t in wins) / len(wins), 4) if wins else 0.0,
            "avg_loss_pct": round(sum(t["pnl_pct"] for t in losses) / len(losses), 4) if losses else 0.0,
            "total_pnl": round(total_pnl, 2),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else float("inf"),
            "best_trade": sorted_by_pnl[-1] if sorted_by_pnl else None,
            "worst_trade": sorted_by_pnl[0] if sorted_by_pnl else None,
        }

    def daily_summary(self, target_date: Optional[str] = None) -> dict:
        """Summary for a specific date (YYYY-MM-DD). Defaults to today."""
        target = target_date or date.today().isoformat()
        all_trades = self._load_trades()
        trades = [t for t in all_trades if t.get("date") == target]
        total_pnl = sum(t["pnl_dollar"] for t in trades)
        wins = [t for t in trades if t["pnl_dollar"] > 0]
        return {
            "date": target,
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(trades) - len(wins),
            "total_pnl": round(total_pnl, 2),
        }
