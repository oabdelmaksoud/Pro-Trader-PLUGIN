"""
CooperCorp PRJ-002 — Portfolio Heat Tracker
Tracks total % of portfolio at risk across all open positions.
Prevents over-concentration in one sector or too much total risk.
"""
import json
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent


class PortfolioHeat:
    """
    Portfolio heat = sum of (position_size / portfolio_value) for all open positions.
    Max heat: 10% (2 positions × 5% each).
    Sector heat: max 7% in any single sector.
    """

    SECTOR_MAP = {
        "NVDA": "semis", "AMD": "semis", "INTC": "semis", "AVGO": "semis",
        "QCOM": "semis", "AMAT": "semis", "LRCX": "semis", "KLAC": "semis",
        "SMCI": "semis", "ARM": "semis", "MRVL": "semis",
        "MSFT": "tech", "AAPL": "tech", "GOOGL": "tech", "META": "tech",
        "AMZN": "tech", "CRM": "tech", "NOW": "tech", "SNOW": "tech",
        "TSLA": "tech", "PLTR": "tech", "CRWD": "tech", "NET": "tech",
        "COIN": "crypto", "HOOD": "fintech", "MSTR": "crypto",
        "JPM": "financials", "GS": "financials", "BAC": "financials",
        "MRNA": "biotech", "BIIB": "biotech", "VRTX": "biotech", "LLY": "biotech",
    }

    MAX_TOTAL_HEAT = 0.12   # 12% total portfolio at risk
    MAX_SECTOR_HEAT = 0.08  # 8% in any single sector

    def __init__(self, broker=None):
        self.broker = broker

    def get_heat(self) -> dict:
        """Calculate current portfolio heat."""
        if not self.broker:
            return {"total_pct": 0, "by_sector": {}, "positions": [], "status": "ok"}

        try:
            account = self.broker.api.get_account()
            portfolio_value = float(account.portfolio_value)
            positions = self.broker.get_positions()

            total_exposure = 0
            sector_exposure = {}
            pos_details = []

            for p in positions:
                sym = p.symbol
                market_val = abs(float(p.market_value))
                pct = market_val / portfolio_value
                sector = self.SECTOR_MAP.get(sym, "other")

                total_exposure += pct
                sector_exposure[sector] = sector_exposure.get(sector, 0) + pct

                pos_details.append({
                    "symbol": sym,
                    "sector": sector,
                    "pct_of_portfolio": round(pct * 100, 2),
                    "market_value": round(market_val, 2),
                })

            # Assess status
            status = "ok"
            if total_exposure > self.MAX_TOTAL_HEAT:
                status = "hot"
            for sector, heat in sector_exposure.items():
                if heat > self.MAX_SECTOR_HEAT:
                    status = "sector_concentrated"
                    break

            return {
                "total_pct": round(total_exposure * 100, 2),
                "by_sector": {k: round(v * 100, 2) for k, v in sector_exposure.items()},
                "positions": pos_details,
                "status": status,
                "portfolio_value": round(portfolio_value, 2),
                "max_total_pct": self.MAX_TOTAL_HEAT * 100,
                "max_sector_pct": self.MAX_SECTOR_HEAT * 100,
            }
        except Exception as e:
            return {"error": str(e), "status": "unknown"}

    def can_add_position(self, symbol: str, position_size_pct: float) -> tuple:
        """
        Check if adding a new position would exceed heat limits.
        Returns (allowed: bool, reason: str)
        """
        heat = self.get_heat()
        if "error" in heat:
            return True, "heat_check_failed"

        new_total = heat["total_pct"] + position_size_pct
        if new_total > self.MAX_TOTAL_HEAT * 100:
            return False, f"Total heat {new_total:.1f}% > max {self.MAX_TOTAL_HEAT*100:.0f}%"

        sector = self.SECTOR_MAP.get(symbol.upper(), "other")
        sector_heat = heat["by_sector"].get(sector, 0) + position_size_pct
        if sector_heat > self.MAX_SECTOR_HEAT * 100:
            return False, f"Sector '{sector}' heat {sector_heat:.1f}% > max {self.MAX_SECTOR_HEAT*100:.0f}%"

        return True, "ok"

    def summary(self) -> str:
        heat = self.get_heat()
        if "error" in heat:
            return f"Portfolio heat: unknown ({heat['error']})"
        status_emoji = {"ok": "🟢", "hot": "🔴", "sector_concentrated": "🟡"}.get(heat["status"], "⚪")
        sectors = " | ".join(f"{s}: {v:.1f}%" for s, v in heat["by_sector"].items())
        return f"{status_emoji} Heat: {heat['total_pct']:.1f}% total | {sectors or 'no positions'}"
