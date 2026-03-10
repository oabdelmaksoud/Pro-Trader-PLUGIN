"""
CooperCorp PRJ-002 — Candlestick Pattern Recognition
Detects 20 candlestick patterns from OHLCV candle data.
No external dependencies — pure math on Candle objects.

Patterns detected:
  Single-candle:  Doji, Hammer, Inverted Hammer, Shooting Star,
                  Marubozu, Spinning Top, High Wave
  Two-candle:     Bullish/Bearish Engulfing, Piercing Line, Dark Cloud,
                  Tweezer Top/Bottom, Harami
  Three-candle:   Morning Star, Evening Star, Three White Soldiers,
                  Three Black Crows, Three Inside Up/Down

Each pattern returns:
  {"name": str, "type": "bullish"|"bearish"|"neutral",
   "strength": 1-3, "index": int}

Usage:
  from tradingagents.technical.candle_patterns import scan_patterns
  patterns = scan_patterns(candles)  # list of Candle objects
"""
from typing import Optional

# Import Candle type
try:
    from tradingagents.technical.candle_builder import Candle
except ImportError:
    Candle = None  # type: ignore


def _body_pct(c) -> float:
    """Body as % of total range."""
    if c.range == 0:
        return 0
    return c.body / c.range


def _avg_body(candles, n: int = 10) -> float:
    """Average body size of last n candles."""
    recent = candles[-n:] if len(candles) >= n else candles
    if not recent:
        return 0
    return sum(c.body for c in recent) / len(recent)


# ---------------------------------------------------------------------------
# Single-candle patterns
# ---------------------------------------------------------------------------

def is_doji(c, avg_body: float) -> Optional[dict]:
    """Body < 10% of range, or body < 10% of average body."""
    if c.range == 0:
        return None
    if _body_pct(c) < 0.10 or (avg_body > 0 and c.body < avg_body * 0.1):
        return {"name": "Doji", "type": "neutral", "strength": 1}
    return None


def is_hammer(c, avg_body: float) -> Optional[dict]:
    """Small body at top, long lower shadow >= 2× body, tiny upper shadow."""
    if c.range == 0 or c.body == 0:
        return None
    if (c.lower_shadow >= 2 * c.body and
            c.upper_shadow <= c.body * 0.3 and
            _body_pct(c) < 0.4):
        return {"name": "Hammer", "type": "bullish", "strength": 2}
    return None


def is_inverted_hammer(c, avg_body: float) -> Optional[dict]:
    """Small body at bottom, long upper shadow >= 2× body, tiny lower shadow."""
    if c.range == 0 or c.body == 0:
        return None
    if (c.upper_shadow >= 2 * c.body and
            c.lower_shadow <= c.body * 0.3 and
            _body_pct(c) < 0.4):
        return {"name": "Inverted Hammer", "type": "bullish", "strength": 1}
    return None


def is_shooting_star(c, avg_body: float) -> Optional[dict]:
    """Same shape as inverted hammer but in uptrend context (handled at call site)."""
    if c.range == 0 or c.body == 0:
        return None
    if (c.upper_shadow >= 2 * c.body and
            c.lower_shadow <= c.body * 0.3 and
            _body_pct(c) < 0.4):
        return {"name": "Shooting Star", "type": "bearish", "strength": 2}
    return None


def is_marubozu(c, avg_body: float) -> Optional[dict]:
    """Full body, very small shadows (< 5% of range)."""
    if c.range == 0:
        return None
    shadow_pct = (c.upper_shadow + c.lower_shadow) / c.range
    if shadow_pct < 0.05 and c.body > avg_body * 1.5:
        typ = "bullish" if c.is_bullish else "bearish"
        return {"name": "Marubozu", "type": typ, "strength": 3}
    return None


def is_spinning_top(c, avg_body: float) -> Optional[dict]:
    """Small body in middle, shadows on both sides roughly equal."""
    if c.range == 0:
        return None
    if (0.1 < _body_pct(c) < 0.35 and
            c.upper_shadow > c.body * 0.5 and
            c.lower_shadow > c.body * 0.5):
        return {"name": "Spinning Top", "type": "neutral", "strength": 1}
    return None


def is_high_wave(c, avg_body: float) -> Optional[dict]:
    """Very small body, very long shadows on both sides."""
    if c.range == 0:
        return None
    if (_body_pct(c) < 0.15 and
            c.upper_shadow > c.body * 3 and
            c.lower_shadow > c.body * 3):
        return {"name": "High Wave", "type": "neutral", "strength": 2}
    return None


# ---------------------------------------------------------------------------
# Two-candle patterns
# ---------------------------------------------------------------------------

def is_bullish_engulfing(prev, cur) -> Optional[dict]:
    """Bearish candle followed by bullish candle that engulfs it."""
    if prev.is_bearish and cur.is_bullish:
        if cur.open <= prev.close and cur.close >= prev.open:
            return {"name": "Bullish Engulfing", "type": "bullish", "strength": 3}
    return None


def is_bearish_engulfing(prev, cur) -> Optional[dict]:
    """Bullish candle followed by bearish candle that engulfs it."""
    if prev.is_bullish and cur.is_bearish:
        if cur.open >= prev.close and cur.close <= prev.open:
            return {"name": "Bearish Engulfing", "type": "bearish", "strength": 3}
    return None


def is_piercing_line(prev, cur) -> Optional[dict]:
    """Bearish candle, then bullish candle opens below prev low, closes above midpoint."""
    if prev.is_bearish and cur.is_bullish:
        mid = (prev.open + prev.close) / 2
        if cur.open < prev.low and cur.close > mid and cur.close < prev.open:
            return {"name": "Piercing Line", "type": "bullish", "strength": 2}
    return None


def is_dark_cloud(prev, cur) -> Optional[dict]:
    """Bullish candle, then bearish candle opens above prev high, closes below midpoint."""
    if prev.is_bullish and cur.is_bearish:
        mid = (prev.open + prev.close) / 2
        if cur.open > prev.high and cur.close < mid and cur.close > prev.open:
            return {"name": "Dark Cloud Cover", "type": "bearish", "strength": 2}
    return None


def is_tweezer_bottom(prev, cur) -> Optional[dict]:
    """Two candles with nearly identical lows at bottom of downtrend."""
    if prev.is_bearish and cur.is_bullish:
        tol = prev.range * 0.05 if prev.range > 0 else 0.01
        if abs(prev.low - cur.low) <= tol:
            return {"name": "Tweezer Bottom", "type": "bullish", "strength": 2}
    return None


def is_tweezer_top(prev, cur) -> Optional[dict]:
    """Two candles with nearly identical highs at top of uptrend."""
    if prev.is_bullish and cur.is_bearish:
        tol = prev.range * 0.05 if prev.range > 0 else 0.01
        if abs(prev.high - cur.high) <= tol:
            return {"name": "Tweezer Top", "type": "bearish", "strength": 2}
    return None


def is_harami(prev, cur) -> Optional[dict]:
    """Second candle's body is contained within first candle's body."""
    if (cur.open > min(prev.open, prev.close) and
            cur.open < max(prev.open, prev.close) and
            cur.close > min(prev.open, prev.close) and
            cur.close < max(prev.open, prev.close)):
        if prev.is_bearish and cur.is_bullish:
            return {"name": "Bullish Harami", "type": "bullish", "strength": 2}
        elif prev.is_bullish and cur.is_bearish:
            return {"name": "Bearish Harami", "type": "bearish", "strength": 2}
    return None


# ---------------------------------------------------------------------------
# Three-candle patterns
# ---------------------------------------------------------------------------

def is_morning_star(c1, c2, c3) -> Optional[dict]:
    """Bearish, small body (gap down), bullish (gap up, closes above c1 midpoint)."""
    if not (c1.is_bearish and c3.is_bullish):
        return None
    mid = (c1.open + c1.close) / 2
    if (c2.body < c1.body * 0.3 and
            c2.close < c1.close and
            c3.close > mid):
        return {"name": "Morning Star", "type": "bullish", "strength": 3}
    return None


def is_evening_star(c1, c2, c3) -> Optional[dict]:
    """Bullish, small body (gap up), bearish (gap down, closes below c1 midpoint)."""
    if not (c1.is_bullish and c3.is_bearish):
        return None
    mid = (c1.open + c1.close) / 2
    if (c2.body < c1.body * 0.3 and
            c2.close > c1.close and
            c3.close < mid):
        return {"name": "Evening Star", "type": "bearish", "strength": 3}
    return None


def is_three_white_soldiers(c1, c2, c3) -> Optional[dict]:
    """Three consecutive bullish candles, each closing higher, small upper shadows."""
    if c1.is_bullish and c2.is_bullish and c3.is_bullish:
        if (c2.close > c1.close and c3.close > c2.close and
                c2.open > c1.open and c3.open > c2.open):
            # Each candle should have small upper shadow
            if all(c.upper_shadow < c.body * 0.3 for c in [c1, c2, c3] if c.body > 0):
                return {"name": "Three White Soldiers", "type": "bullish", "strength": 3}
    return None


def is_three_black_crows(c1, c2, c3) -> Optional[dict]:
    """Three consecutive bearish candles, each closing lower."""
    if c1.is_bearish and c2.is_bearish and c3.is_bearish:
        if (c2.close < c1.close and c3.close < c2.close and
                c2.open < c1.open and c3.open < c2.open):
            if all(c.lower_shadow < c.body * 0.3 for c in [c1, c2, c3] if c.body > 0):
                return {"name": "Three Black Crows", "type": "bearish", "strength": 3}
    return None


def is_three_inside_up(c1, c2, c3) -> Optional[dict]:
    """Bearish, bullish harami inside c1, then bullish closes above c1 open."""
    if c1.is_bearish and c2.is_bullish and c3.is_bullish:
        if (c2.open > c1.close and c2.close < c1.open and
                c3.close > c1.open):
            return {"name": "Three Inside Up", "type": "bullish", "strength": 3}
    return None


def is_three_inside_down(c1, c2, c3) -> Optional[dict]:
    """Bullish, bearish harami inside c1, then bearish closes below c1 open."""
    if c1.is_bullish and c2.is_bearish and c3.is_bearish:
        if (c2.open < c1.close and c2.close > c1.open and
                c3.close < c1.open):
            return {"name": "Three Inside Down", "type": "bearish", "strength": 3}
    return None


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _is_uptrend(candles, lookback: int = 5) -> bool:
    """Simple trend: are recent closes generally rising?"""
    if len(candles) < lookback:
        return False
    recent = candles[-lookback:]
    rising = sum(1 for i in range(1, len(recent)) if recent[i].close > recent[i - 1].close)
    return rising >= lookback * 0.6


def _is_downtrend(candles, lookback: int = 5) -> bool:
    if len(candles) < lookback:
        return False
    recent = candles[-lookback:]
    falling = sum(1 for i in range(1, len(recent)) if recent[i].close < recent[i - 1].close)
    return falling >= lookback * 0.6


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def scan_patterns(candles: list, max_lookback: int = 3) -> list[dict]:
    """
    Scan a list of Candle objects for all recognized patterns.
    Returns list of pattern dicts, most recent first.
    Each dict: {name, type, strength, index, context}
    """
    if len(candles) < 2:
        return []

    results = []
    avg_b = _avg_body(candles)
    uptrend = _is_uptrend(candles)
    downtrend = _is_downtrend(candles)

    # Scan last `max_lookback` candles for patterns
    end = len(candles)
    start = max(0, end - max_lookback)

    for i in range(start, end):
        c = candles[i]
        context = "uptrend" if uptrend else ("downtrend" if downtrend else "range")

        # Single-candle
        for fn in [is_doji, is_marubozu, is_spinning_top, is_high_wave]:
            p = fn(c, avg_b)
            if p:
                p["index"] = i
                p["context"] = context
                results.append(p)

        # Hammer vs Shooting Star depends on trend
        if downtrend:
            p = is_hammer(c, avg_b)
            if p:
                p["index"] = i
                p["context"] = context
                results.append(p)
            p = is_inverted_hammer(c, avg_b)
            if p:
                p["index"] = i
                p["context"] = context
                results.append(p)

        if uptrend:
            p = is_shooting_star(c, avg_b)
            if p:
                p["index"] = i
                p["context"] = context
                results.append(p)

        # Two-candle
        if i >= 1:
            prev = candles[i - 1]
            for fn in [is_bullish_engulfing, is_bearish_engulfing,
                       is_piercing_line, is_dark_cloud,
                       is_tweezer_bottom, is_tweezer_top, is_harami]:
                p = fn(prev, c)
                if p:
                    p["index"] = i
                    p["context"] = context
                    results.append(p)

        # Three-candle
        if i >= 2:
            c1, c2, c3 = candles[i - 2], candles[i - 1], c
            for fn in [is_morning_star, is_evening_star,
                       is_three_white_soldiers, is_three_black_crows,
                       is_three_inside_up, is_three_inside_down]:
                p = fn(c1, c2, c3)
                if p:
                    p["index"] = i
                    p["context"] = context
                    results.append(p)

    return results


def summarize_patterns(patterns: list[dict]) -> str:
    """Format pattern list as a readable string."""
    if not patterns:
        return "No patterns detected"
    lines = []
    icons = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
    stars = {1: "★", 2: "★★", 3: "★★★"}
    for p in patterns:
        icon = icons.get(p["type"], "⚪")
        strength = stars.get(p["strength"], "★")
        lines.append(f"{icon} {p['name']} ({p['type']}) {strength} [{p.get('context', '')}]")
    return "\n".join(lines)
