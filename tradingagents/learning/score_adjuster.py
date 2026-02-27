"""
CooperCorp PRJ-002 — Score Adjuster
Applies dynamic pattern-based adjustments to entry scoring.
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tradingagents.learning.pattern_tracker import PatternTracker

logger = logging.getLogger(__name__)


class ScoreAdjuster:
    """
    Applies dynamic pattern-based adjustments to base entry scores.
    Loaded at scan time to incorporate lessons learned.
    """

    def apply(self, base_scores: dict, pattern_tracker: "PatternTracker") -> dict:
        """
        Modifies base scores based on active pattern adjustments.

        base_scores = {
            "catalyst": float,
            "technical": float,
            "sentiment": float,
            "fundamental": float,
            "rr": float,
            # optional context fields:
            "pct_from_open": float,      # for chase detection
            "volume_vs_avg": float,      # for volume check (>1.0 = above avg)
            "macro_bearish": bool,
            "rr_ratio": float,
            "sentiment_extreme_bullish": bool,
        }

        Returns adjusted scores dict.
        """
        adjustments = pattern_tracker.get_score_adjustments()
        scores = dict(base_scores)

        # --- Chase breakout penalty ---
        if adjustments.get("no_chase_bonus"):
            pct_from_open = scores.get("pct_from_open", 0)
            if pct_from_open > 0.03:  # >3% from open without pullback
                penalty = adjustments["no_chase_bonus"]
                scores["technical"] = scores.get("technical", 0) + penalty
                logger.info(f"ScoreAdjuster: chase penalty {penalty} applied (pct_from_open={pct_from_open:.1%})")

        if adjustments.get("technical_cap_on_chase"):
            pct_from_open = scores.get("pct_from_open", 0)
            if pct_from_open > 0.03:
                cap = adjustments["technical_cap_on_chase"]
                scores["technical"] = min(scores.get("technical", 0), cap)
                logger.info(f"ScoreAdjuster: technical capped at {cap} due to chase pattern")

        # --- Earnings block ---
        if adjustments.get("earnings_block"):
            # If earnings_penalty is already applied in base_scores, amplify
            if scores.get("earnings_imminent", False):
                scores["catalyst"] = min(scores.get("catalyst", 0) - 2.0, 0)
                logger.info("ScoreAdjuster: earnings block applied")

        if adjustments.get("earnings_penalty_boost"):
            if scores.get("earnings_imminent", False):
                scores["catalyst"] = scores.get("catalyst", 0) + adjustments["earnings_penalty_boost"]

        # --- Volume confirmation ---
        if adjustments.get("volume_confirmation_required"):
            volume_ratio = scores.get("volume_vs_avg", 1.0)
            if volume_ratio < 1.0:
                scores["technical"] = scores.get("technical", 0) - 1.0
                logger.info(f"ScoreAdjuster: volume penalty applied (ratio={volume_ratio:.2f})")

        # --- Macro weight boost ---
        if adjustments.get("macro_weight_multiplier"):
            macro_score = scores.get("fundamental", 0)
            multiplier = adjustments["macro_weight_multiplier"]
            scores["fundamental"] = macro_score * multiplier
            logger.info(f"ScoreAdjuster: macro weight multiplied by {multiplier}")

        if adjustments.get("macro_veto_on_bearish"):
            if scores.get("macro_bearish", False):
                # Hard veto: set total to 0 (will cause HOLD)
                scores["_macro_veto"] = True
                logger.warning("ScoreAdjuster: MACRO VETO — macro is bearish, trade blocked")

        # --- R/R enforcement ---
        if adjustments.get("min_rr_required"):
            rr = scores.get("rr_ratio", 0)
            min_rr = adjustments["min_rr_required"]
            if rr < min_rr:
                scores["rr"] = min(scores.get("rr", 0), 1.0)  # Penalize RR score
                logger.info(f"ScoreAdjuster: R/R {rr:.1f} below min {min_rr}, penalized")

        # --- Catalyst minimum ---
        if adjustments.get("catalyst_min_score"):
            cat = scores.get("catalyst", 0)
            if cat < adjustments["catalyst_min_score"]:
                scores["catalyst"] = max(cat - 1.0, 1.0)
                logger.info(f"ScoreAdjuster: weak catalyst penalized ({cat})")

        # --- Sentiment cap ---
        if adjustments.get("sentiment_cap"):
            if scores.get("sentiment_extreme_bullish", False):
                cap = adjustments["sentiment_cap"]
                scores["sentiment"] = min(scores.get("sentiment", 0), cap)
                logger.info(f"ScoreAdjuster: sentiment capped at {cap} (extreme bullish)")

        # --- Valuation penalty ---
        if adjustments.get("valuation_penalty"):
            if scores.get("extended_valuation", False):
                scores["fundamental"] = scores.get("fundamental", 0) + adjustments["valuation_penalty"]

        # --- Sector headwind ---
        if adjustments.get("sector_check_required"):
            if scores.get("sector_downtrend", False):
                scores["fundamental"] = scores.get("fundamental", 0) - 1.0
                logger.info("ScoreAdjuster: sector headwind penalty applied")

        return scores

    def get_active_rules(self) -> list:
        """Returns human-readable list of current adjustment rules."""
        from tradingagents.learning.pattern_tracker import PatternTracker
        pt = PatternTracker()
        return pt.get_adjustment_summary()
