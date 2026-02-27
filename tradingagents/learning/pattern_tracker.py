"""
CooperCorp PRJ-002 — Pattern Tracker
Tracks recurring mistake patterns and generates dynamic scoring adjustments.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
ADJUSTMENTS_FILE = REPO_ROOT / "logs" / "score_adjustments.json"
PATTERNS_HISTORY_FILE = REPO_ROOT / "logs" / "pattern_history.jsonl"


class PatternTracker:
    """
    Tracks recurring mistake patterns and adjusts scoring weights.
    """

    ADJUSTMENTS_FILE = ADJUSTMENTS_FILE

    # Known patterns to detect
    PATTERNS = {
        "chased_breakout": "Entered after >3% move without pullback",
        "pre_earnings_entry": "Entered 1 day before earnings",
        "low_volume_breakout": "Breakout on below-average volume",
        "macro_ignored": "Strong bearish macro context ignored",
        "extended_valuation": "Entered highly extended stock (P/E >50x vs sector)",
        "weak_catalyst": "Catalyst was minor/already priced in",
        "poor_rr": "Risk/reward was below 2:1 at entry",
        "sentiment_peak": "Entered when social sentiment was at extreme bullish",
        "sector_headwind": "Sector was in downtrend at time of entry",
        "held_too_long": "Target was hit but not taken, turned into loser",
    }

    # Adjustment rules: pattern → what to apply to scoring, keyed by threshold count
    ADJUSTMENT_RULES = {
        "chased_breakout": {
            2: {"no_chase_bonus": -1.0, "description": "Penalize entries on extended moves"},
            3: {"no_chase_bonus": -1.5, "technical_cap_on_chase": 2, "description": "Cap technical score at 2 if stock >3% from open without pullback"},
        },
        "pre_earnings_entry": {
            2: {"earnings_penalty_boost": -1.0, "description": "Add extra earnings penalty"},
            3: {"earnings_block": True, "description": "Block entries within 1 day of earnings"},
        },
        "low_volume_breakout": {
            2: {"volume_confirmation_required": True, "description": "Require above-avg volume for breakouts"},
        },
        "macro_ignored": {
            2: {"macro_weight_multiplier": 1.5, "description": "Increase macro weight by 1.5x"},
            3: {"macro_weight_multiplier": 2.0, "macro_veto_on_bearish": True, "description": "Macro veto: block trades if macro is bearish"},
        },
        "poor_rr": {
            2: {"min_rr_required": 2.0, "description": "Require minimum 2:1 R/R"},
            3: {"min_rr_required": 2.5, "description": "Require minimum 2.5:1 R/R"},
        },
        "held_too_long": {
            2: {"time_stop_hours": 4, "description": "Add 4-hour time stop"},
        },
        "weak_catalyst": {
            2: {"catalyst_min_score": 3, "description": "Require catalyst score >= 3"},
        },
        "sentiment_peak": {
            2: {"sentiment_cap": 3, "description": "Cap sentiment score at 3 when extreme bullish"},
        },
        "sector_headwind": {
            2: {"sector_check_required": True, "description": "Block trades when sector in downtrend"},
        },
        "extended_valuation": {
            2: {"valuation_penalty": -1.0, "description": "Apply -1 score for highly extended valuations"},
        },
    }

    def record_pattern(self, pattern: str, trade: dict):
        """Record a pattern occurrence to history and update adjustments."""
        if pattern not in self.PATTERNS:
            logger.warning(f"Unknown pattern: {pattern}")
            return

        PATTERNS_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "pattern": pattern,
            "ticker": trade.get("ticker", "?"),
            "date": trade.get("date", ""),
            "pnl_pct": trade.get("pnl_pct", 0),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(PATTERNS_HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

        # Recompute adjustments after recording
        self._recompute_adjustments()
        logger.info(f"Pattern recorded: {pattern} for {trade.get('ticker', '?')}")

    def _load_history(self) -> list:
        if not PATTERNS_HISTORY_FILE.exists():
            return []
        entries = []
        with open(PATTERNS_HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        return entries

    def _count_patterns(self) -> dict:
        history = self._load_history()
        counts = {}
        for entry in history:
            pat = entry["pattern"]
            counts[pat] = counts.get(pat, 0) + 1
        return counts

    def _recompute_adjustments(self):
        """Recompute and save score_adjustments.json based on current pattern counts."""
        counts = self._count_patterns()
        adjustments = {}

        for pattern, count in counts.items():
            rules = self.ADJUSTMENT_RULES.get(pattern, {})
            # Apply the highest threshold that's been crossed
            applied_rule = {}
            for threshold in sorted(rules.keys()):
                if count >= threshold:
                    applied_rule = rules[threshold].copy()
            if applied_rule:
                adjustments[pattern] = {
                    "count": count,
                    "rule": applied_rule,
                }

        ADJUSTMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ADJUSTMENTS_FILE, "w") as f:
            json.dump(adjustments, f, indent=2)

    def get_recurring(self, min_count=2) -> list:
        """Returns patterns that have occurred >= min_count times."""
        counts = self._count_patterns()
        return [
            {"pattern": pat, "count": cnt, "description": self.PATTERNS.get(pat, "")}
            for pat, cnt in counts.items()
            if cnt >= min_count
        ]

    def get_score_adjustments(self) -> dict:
        """
        Returns dynamic adjustments to scoring weights based on patterns.
        e.g. {"no_chase_bonus": -1.5, "min_rr_required": 2.0, ...}
        """
        if not ADJUSTMENTS_FILE.exists():
            self._recompute_adjustments()
        if not ADJUSTMENTS_FILE.exists():
            return {}
        try:
            with open(ADJUSTMENTS_FILE) as f:
                raw = json.load(f)
            # Flatten: merge all active rules into a single dict
            flat = {}
            for pattern_data in raw.values():
                rule = pattern_data.get("rule", {})
                for k, v in rule.items():
                    if k != "description":
                        flat[k] = v
            return flat
        except Exception:
            return {}

    def get_adjustment_summary(self) -> list:
        """Returns human-readable list of active adjustments."""
        if not ADJUSTMENTS_FILE.exists():
            return []
        try:
            with open(ADJUSTMENTS_FILE) as f:
                raw = json.load(f)
            lines = []
            for pattern, data in raw.items():
                desc = data.get("rule", {}).get("description", "")
                count = data.get("count", 0)
                lines.append(f"- **{pattern}** ({count}x): {desc}")
            return lines
        except Exception:
            return []
