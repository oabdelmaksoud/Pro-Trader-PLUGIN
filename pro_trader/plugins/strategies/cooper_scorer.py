"""Cooper Scorer — the default strategy plugin wrapping existing scoring logic."""

from __future__ import annotations
import logging

from pro_trader.core.interfaces import StrategyPlugin
from pro_trader.models.signal import Signal, Direction
from pro_trader.models.market_data import MarketData

logger = logging.getLogger(__name__)


class CooperScorer(StrategyPlugin):
    name = "cooper_scorer"
    version = "1.0.0"
    description = "CooperCorp composite scoring strategy"

    def __init__(self):
        self._threshold = 7.0
        self._conviction_min = 7

    def configure(self, config: dict) -> None:
        self._threshold = config.get("threshold", 7.0)
        self._conviction_min = config.get("conviction_min", 7)

    def evaluate(self, data: MarketData, reports: dict[str, dict],
                 context: dict | None = None) -> Signal:
        # ── Base score from technicals ────────────────────────────────
        score = 5.0
        tech = data.technicals

        if tech:
            if tech.above_sma20:
                score += 0.3
            if tech.above_sma50:
                score += 0.3
            if tech.rsi and 45 < tech.rsi < 70:
                score += 0.4
            if tech.volume_ratio > 1.5:
                score += 0.5
            if tech.volume_ratio > 2.5:
                score += 0.3
            if tech.macd_cross == "bullish":
                score += 0.7
            if tech.bb_squeeze:
                score += 0.4
            change = data.quote.change_pct if data.quote else 0
            if 1 < change < 5:
                score += 0.3
            elif change > 5:
                score += 0.5

        # ── Futures-specific adjustments ──────────────────────────────
        if data.asset_type == "futures" and data.contract_spec:
            margin = data.contract_spec.get("margin", 0)
            asset_class = data.contract_spec.get("asset_class", "")
            if 0 < margin <= 300:
                score += 0.5
            elif margin <= 500:
                score += 0.3
            elif margin > 1000:
                score -= 0.3
            if asset_class in ("index", "fx"):
                score += 0.2

        # ── Analyst report scores ─────────────────────────────────────
        analyst_scores = []
        for name, report in reports.items():
            if isinstance(report, dict) and "score" in report:
                analyst_scores.append(report["score"])

        if analyst_scores:
            avg_analyst = sum(analyst_scores) / len(analyst_scores)
            # Blend: 40% technical base + 60% analyst average
            score = score * 0.4 + avg_analyst * 0.6

        # ── Determine direction ───────────────────────────────────────
        directions = []
        for report in reports.values():
            if isinstance(report, dict):
                d = report.get("direction", "HOLD")
                directions.append(d)

        buy_count = sum(1 for d in directions if d == "BUY")
        sell_count = sum(1 for d in directions if d == "SELL")

        if buy_count > sell_count:
            direction = Direction.BUY
        elif sell_count > buy_count:
            direction = Direction.SELL
        else:
            direction = Direction.HOLD

        # ── Confidence from consensus ─────────────────────────────────
        total = len(directions) or 1
        consensus = max(buy_count, sell_count) / total
        confidence = min(10, int(consensus * 10 + (score - 5) * 0.5))
        confidence = max(1, confidence)

        score = min(10.0, max(0.0, score))

        # ── Profile-driven adjustments ──────────────────────────────
        profile = (context or {}).get("trader_profile", {})
        position_pct = 0.15  # default 15% of account

        risk_tolerance = profile.get("risk_tolerance", "moderate")
        if risk_tolerance == "conservative":
            # Require higher score for conservative traders
            if score < 7.5:
                score -= 0.3
            position_pct = 0.10
        elif risk_tolerance == "aggressive":
            position_pct = 0.20

        # Recovery mode: tighten requirements for high-probability trades
        if profile.get("recovery_mode"):
            rec_strategy = profile.get("recovery_strategy", "moderate")
            if rec_strategy == "conservative_rebuild":
                if score < 7.5:
                    score -= 0.5
                position_pct = min(position_pct, 0.10)
            elif rec_strategy == "aggressive":
                position_pct = min(position_pct + 0.05, 0.25)

        # Trading style affects holding period metadata
        trading_style = profile.get("trading_style", "swing")

        # Experience: beginners get tighter scoring
        if profile.get("experience_level") == "beginner":
            if score < 7.5:
                score -= 0.3
            position_pct = min(position_pct, 0.10)

        score = min(10.0, max(0.0, score))

        # Position size based on account and risk
        account_value = (context or {}).get("account_value", 500)
        position_size = max(1, int(account_value * position_pct / max(data.price, 1)))

        # Stop/target based on profile risk tolerance
        stop_pct = profile.get("max_loss_per_trade_pct", 2.0) / 100
        target_map = {"conservative": 0.05, "moderate": 0.08, "aggressive": 0.12}
        target_pct = target_map.get(risk_tolerance, 0.08)

        stop_loss = round(data.price * (1 - stop_pct), 2) if data.price else None
        take_profit = round(data.price * (1 + target_pct), 2) if data.price else None

        return Signal(
            ticker=data.ticker,
            direction=direction,
            score=round(score, 1),
            confidence=confidence,
            price=data.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            asset_type=data.asset_type,
            analyst_reports=reports,
            source="cooper_scorer",
            metadata={
                "base_score": 5.0,
                "analyst_scores": analyst_scores,
                "is_futures": data.asset_type == "futures",
                "risk_tolerance": risk_tolerance,
                "trading_style": trading_style,
                "recovery_mode": profile.get("recovery_mode", False),
                "position_pct": position_pct,
            },
        )
