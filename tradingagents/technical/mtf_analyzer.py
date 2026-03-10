"""
CooperCorp PRJ-002 — Multi-Timeframe Confluence Analyzer
Analyzes candle + chart patterns across ALL timeframes simultaneously,
then produces a single confluence score that reflects what a human trader
would see looking at multiple chart windows.

Timeframes analyzed: 1m, 5m, 15m, 1h, 4h, 1d
Weight distribution: higher timeframes carry more weight.

Confluence Score (-10 to +10):
  +7 to +10:  Strong bullish confluence (all TFs align bullish)
  +3 to +6:   Moderate bullish
   0 to +2:   Weak / mixed
  -2 to  0:   Weak / mixed
  -6 to -3:   Moderate bearish
 -10 to -7:   Strong bearish confluence (all TFs align bearish)

Usage:
  analyzer = MTFAnalyzer()
  # Feed ticks as they come in
  analyzer.on_tick("NVDA", price=135.50, size=100)
  # Get analysis
  result = analyzer.analyze("NVDA")
  print(result["score"])       # -7.2
  print(result["bias"])        # "strong_bearish"
  print(result["summary"])     # human-readable
  print(result["timeframes"])  # per-TF breakdown
"""
import time
from typing import Optional

from tradingagents.technical.candle_builder import CandleBuilder, TIMEFRAMES
from tradingagents.technical.candle_patterns import scan_patterns, summarize_patterns
from tradingagents.technical.chart_patterns import (
    scan_chart_patterns,
    find_support_resistance,
    summarize_chart_patterns,
)

# Higher timeframes = more weight
TF_WEIGHTS = {
    "1m": 0.05,
    "5m": 0.10,
    "15m": 0.15,
    "1h": 0.25,
    "4h": 0.25,
    "1d": 0.20,
}

# Minimum candles needed per TF for meaningful analysis
MIN_CANDLES = {
    "1m": 20,
    "5m": 15,
    "15m": 10,
    "1h": 8,
    "4h": 5,
    "1d": 5,
}


class MTFAnalyzer:
    """
    Multi-timeframe technical analysis engine.
    Maintains CandleBuilders per symbol and runs pattern detection
    across all timeframes on demand.
    """

    def __init__(self):
        self.builders: dict[str, CandleBuilder] = {}

    def _get_builder(self, symbol: str) -> CandleBuilder:
        sym = symbol.upper()
        if sym not in self.builders:
            self.builders[sym] = CandleBuilder(sym)
        return self.builders[sym]

    def on_tick(self, symbol: str, price: float, size: int = 1,
                timestamp: float = None) -> list:
        """
        Feed a raw tick. Returns list of (timeframe, candle) for any
        candles that just completed (useful for triggering pattern scans).
        """
        builder = self._get_builder(symbol)
        return builder.on_tick(price, size, timestamp)

    def analyze(self, symbol: str) -> dict:
        """
        Run full multi-timeframe analysis for a symbol.
        Returns comprehensive analysis dict.
        """
        builder = self._get_builder(symbol)
        tf_results = {}
        weighted_score = 0.0
        total_weight = 0.0

        for tf, weight in TF_WEIGHTS.items():
            candles = builder.get_candles(tf, count=100)
            current = builder.get_current(tf)
            min_needed = MIN_CANDLES.get(tf, 10)

            if len(candles) < min_needed:
                tf_results[tf] = {
                    "status": "insufficient_data",
                    "candle_count": len(candles),
                    "needed": min_needed,
                    "score": 0,
                }
                continue

            # Run candle pattern detection
            candle_pats = scan_patterns(candles)

            # Run chart pattern detection (only on 5m+ timeframes)
            chart_pats = []
            sr_levels = {"support": [], "resistance": []}
            if tf != "1m" and len(candles) >= 15:
                chart_pats = scan_chart_patterns(candles)
                o, h, l, c, v = builder.get_ohlcv_arrays(tf, count=100)
                sr_levels = find_support_resistance(h, l, c)

            # Compute TF score from patterns
            tf_score = self._score_patterns(candles, candle_pats, chart_pats)

            # Trend context
            trend = self._assess_trend(candles)

            tf_results[tf] = {
                "status": "ok",
                "candle_count": len(candles),
                "score": round(tf_score, 2),
                "trend": trend,
                "candle_patterns": candle_pats,
                "chart_patterns": chart_pats,
                "support_resistance": sr_levels,
                "current_candle": current.to_dict() if current else None,
            }

            weighted_score += tf_score * weight
            total_weight += weight

        # Normalize
        final_score = (weighted_score / total_weight * 10) if total_weight > 0 else 0
        final_score = max(-10, min(10, final_score))

        # Determine bias
        if final_score >= 7:
            bias = "strong_bullish"
        elif final_score >= 3:
            bias = "moderate_bullish"
        elif final_score >= 0:
            bias = "weak_bullish"
        elif final_score >= -3:
            bias = "weak_bearish"
        elif final_score >= -7:
            bias = "moderate_bearish"
        else:
            bias = "strong_bearish"

        # Confluence check: do multiple TFs agree?
        scored_tfs = [r for r in tf_results.values() if r["status"] == "ok"]
        bullish_tfs = sum(1 for r in scored_tfs if r["score"] > 0.2)
        bearish_tfs = sum(1 for r in scored_tfs if r["score"] < -0.2)
        total_scored = len(scored_tfs)
        confluence = "none"
        if total_scored > 0:
            if bullish_tfs / total_scored >= 0.7:
                confluence = "bullish_aligned"
            elif bearish_tfs / total_scored >= 0.7:
                confluence = "bearish_aligned"
            elif bullish_tfs > 0 and bearish_tfs > 0:
                confluence = "mixed"
            else:
                confluence = "neutral"

        summary = self._build_summary(symbol, final_score, bias, confluence, tf_results)

        return {
            "symbol": symbol.upper(),
            "score": round(final_score, 2),
            "bias": bias,
            "confluence": confluence,
            "bullish_tfs": bullish_tfs,
            "bearish_tfs": bearish_tfs,
            "total_tfs": total_scored,
            "timeframes": tf_results,
            "summary": summary,
            "timestamp": time.time(),
        }

    def _score_patterns(self, candles, candle_pats: list, chart_pats: list) -> float:
        """
        Convert patterns into a -1 to +1 score.
        Bullish patterns add, bearish subtract, weighted by strength.
        """
        score = 0.0

        # Candle patterns (strength 1-3)
        for p in candle_pats:
            mult = p["strength"] / 3.0  # normalize to 0-1
            if p["type"] == "bullish":
                score += mult * 0.3
            elif p["type"] == "bearish":
                score -= mult * 0.3

        # Chart patterns (weighted by confidence)
        for p in chart_pats:
            conf = p.get("confidence", 0.5)
            if p["type"] == "bullish":
                score += conf * 0.5
            elif p["type"] == "bearish":
                score -= conf * 0.5

        # Trend momentum bonus
        if len(candles) >= 5:
            recent = candles[-5:]
            closes_rising = sum(1 for i in range(1, len(recent)) if recent[i].close > recent[i-1].close)
            if closes_rising >= 4:
                score += 0.2
            elif closes_rising <= 1:
                score -= 0.2

        return max(-1.0, min(1.0, score))

    def _assess_trend(self, candles) -> str:
        """Simple trend assessment from recent candles."""
        if len(candles) < 10:
            return "unknown"
        recent_10 = candles[-10:]
        recent_5 = candles[-5:]

        # SMA proxy
        sma10 = sum(c.close for c in recent_10) / 10
        sma5 = sum(c.close for c in recent_5) / 5
        current = candles[-1].close

        if current > sma5 > sma10:
            return "uptrend"
        elif current < sma5 < sma10:
            return "downtrend"
        elif abs(current - sma10) / sma10 < 0.005:
            return "sideways"
        else:
            return "mixed"

    def _build_summary(self, symbol: str, score: float, bias: str,
                       confluence: str, tf_results: dict) -> str:
        """Build human-readable analysis summary."""
        lines = [f"MTF Analysis: {symbol.upper()} — Score: {score:+.1f} ({bias})"]
        lines.append(f"Confluence: {confluence}")
        lines.append("")

        for tf in ["1d", "4h", "1h", "15m", "5m", "1m"]:
            r = tf_results.get(tf, {})
            if r.get("status") == "insufficient_data":
                lines.append(f"  {tf:>3}: ⏳ need {r['needed']} candles (have {r['candle_count']})")
                continue
            if r.get("status") != "ok":
                continue

            trend = r.get("trend", "?")
            tf_score = r.get("score", 0)
            arrow = "▲" if tf_score > 0.1 else "▼" if tf_score < -0.1 else "—"

            n_candle = len(r.get("candle_patterns", []))
            n_chart = len(r.get("chart_patterns", []))

            lines.append(f"  {tf:>3}: {arrow} {tf_score:+.2f} | trend: {trend} | "
                         f"candle: {n_candle} pats | chart: {n_chart} pats")

            # Show significant patterns
            for p in r.get("candle_patterns", []):
                if p["strength"] >= 2:
                    icon = "🟢" if p["type"] == "bullish" else "🔴" if p["type"] == "bearish" else "⚪"
                    lines.append(f"        {icon} {p['name']} (str={p['strength']})")

            for p in r.get("chart_patterns", []):
                icon = "🟢" if p["type"] == "bullish" else "🔴" if p["type"] == "bearish" else "⚪"
                conf = int(p.get("confidence", 0) * 100)
                tgt = p.get("target_price", 0)
                lines.append(f"        {icon} {p['name']} → ${tgt:.2f} ({conf}%)")

        return "\n".join(lines)

    def get_quick_bias(self, symbol: str) -> tuple[float, str]:
        """
        Quick score + bias without full analysis.
        Returns (score, bias_string).
        """
        result = self.analyze(symbol)
        return result["score"], result["bias"]

    def flush(self, symbol: str = None):
        """Persist all candle data to disk."""
        if symbol:
            builder = self.builders.get(symbol.upper())
            if builder:
                builder.flush_all()
        else:
            for builder in self.builders.values():
                builder.flush_all()
