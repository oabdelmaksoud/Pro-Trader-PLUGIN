"""
CooperCorp PRJ-002 — Chart Pattern Recognition
Detects classic chart patterns from OHLCV candle arrays.
No external dependencies — pure math.

Patterns detected:
  Reversal:   Head & Shoulders, Inverse H&S, Double Top, Double Bottom
  Continuation: Bull/Bear Flag, Ascending/Descending Triangle,
                Symmetrical Triangle, Rising/Falling Wedge
  Breakout:   Support/Resistance break, Channel breakout

Each pattern returns:
  {"name": str, "type": "bullish"|"bearish",
   "strength": 1-3, "start_idx": int, "end_idx": int,
   "target_price": float (projected), "confidence": float 0-1}

Usage:
  from tradingagents.technical.chart_patterns import scan_chart_patterns
  patterns = scan_chart_patterns(candles)
"""
import math
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_pivots(highs: list, lows: list, window: int = 5):
    """
    Find pivot highs and pivot lows.
    A pivot high is a high that is the highest in ±window bars.
    Returns (pivot_highs, pivot_lows) as lists of (index, price).
    """
    n = len(highs)
    ph, pl = [], []
    for i in range(window, n - window):
        if highs[i] == max(highs[i - window:i + window + 1]):
            ph.append((i, highs[i]))
        if lows[i] == min(lows[i - window:i + window + 1]):
            pl.append((i, lows[i]))
    return ph, pl


def _linear_regression(points: list[tuple]) -> tuple:
    """
    Simple linear regression on (x, y) points.
    Returns (slope, intercept, r_squared).
    """
    n = len(points)
    if n < 2:
        return 0, 0, 0
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] ** 2 for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0, sy / n, 0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    # R-squared
    y_mean = sy / n
    ss_tot = sum((p[1] - y_mean) ** 2 for p in points)
    ss_res = sum((p[1] - (slope * p[0] + intercept)) ** 2 for p in points)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    return slope, intercept, r2


def _tol_equal(a: float, b: float, pct: float = 0.015) -> bool:
    """Check if two values are within pct% of each other."""
    if a == 0 and b == 0:
        return True
    avg = (abs(a) + abs(b)) / 2
    return abs(a - b) / avg <= pct if avg > 0 else True


# ---------------------------------------------------------------------------
# Support / Resistance
# ---------------------------------------------------------------------------

def find_support_resistance(highs: list, lows: list, closes: list,
                            window: int = 5, tolerance: float = 0.02) -> dict:
    """
    Find key support and resistance levels from pivot points.
    Groups nearby pivots within tolerance%.
    Returns {"support": [(price, touches)], "resistance": [(price, touches)]}.
    """
    pivot_highs, pivot_lows = _find_pivots(highs, lows, window)

    def cluster(pivots, tol):
        if not pivots:
            return []
        sorted_p = sorted(pivots, key=lambda x: x[1])
        clusters = []
        current = [sorted_p[0]]
        for p in sorted_p[1:]:
            if _tol_equal(p[1], current[0][1], tol):
                current.append(p)
            else:
                avg_price = sum(x[1] for x in current) / len(current)
                clusters.append((round(avg_price, 4), len(current)))
                current = [p]
        if current:
            avg_price = sum(x[1] for x in current) / len(current)
            clusters.append((round(avg_price, 4), len(current)))
        return sorted(clusters, key=lambda x: -x[1])

    return {
        "resistance": cluster(pivot_highs, tolerance),
        "support": cluster(pivot_lows, tolerance),
    }


# ---------------------------------------------------------------------------
# Double Top / Double Bottom
# ---------------------------------------------------------------------------

def detect_double_top(highs: list, lows: list, closes: list,
                      window: int = 5) -> Optional[dict]:
    """Two peaks at roughly same level with a valley between."""
    pivot_highs, _ = _find_pivots(highs, lows, window)
    if len(pivot_highs) < 2:
        return None

    # Check last two pivot highs
    for i in range(len(pivot_highs) - 1, 0, -1):
        p2_idx, p2_price = pivot_highs[i]
        p1_idx, p1_price = pivot_highs[i - 1]

        if p2_idx - p1_idx < window * 2:
            continue

        if _tol_equal(p1_price, p2_price, 0.02):
            # Find neckline (lowest low between peaks)
            between_lows = lows[p1_idx:p2_idx + 1]
            if not between_lows:
                continue
            neckline = min(between_lows)
            height = p1_price - neckline
            target = neckline - height  # measured move down

            # Confirm: price should be dropping after p2
            if p2_idx < len(closes) - 1 and closes[-1] < p2_price:
                return {
                    "name": "Double Top",
                    "type": "bearish",
                    "strength": 3,
                    "start_idx": p1_idx,
                    "end_idx": p2_idx,
                    "neckline": round(neckline, 4),
                    "target_price": round(target, 4),
                    "confidence": 0.7,
                }
    return None


def detect_double_bottom(highs: list, lows: list, closes: list,
                         window: int = 5) -> Optional[dict]:
    """Two troughs at roughly same level with a peak between."""
    _, pivot_lows = _find_pivots(highs, lows, window)
    if len(pivot_lows) < 2:
        return None

    for i in range(len(pivot_lows) - 1, 0, -1):
        p2_idx, p2_price = pivot_lows[i]
        p1_idx, p1_price = pivot_lows[i - 1]

        if p2_idx - p1_idx < window * 2:
            continue

        if _tol_equal(p1_price, p2_price, 0.02):
            between_highs = highs[p1_idx:p2_idx + 1]
            if not between_highs:
                continue
            neckline = max(between_highs)
            height = neckline - p1_price
            target = neckline + height

            if p2_idx < len(closes) - 1 and closes[-1] > p2_price:
                return {
                    "name": "Double Bottom",
                    "type": "bullish",
                    "strength": 3,
                    "start_idx": p1_idx,
                    "end_idx": p2_idx,
                    "neckline": round(neckline, 4),
                    "target_price": round(target, 4),
                    "confidence": 0.7,
                }
    return None


# ---------------------------------------------------------------------------
# Head & Shoulders
# ---------------------------------------------------------------------------

def detect_head_shoulders(highs: list, lows: list, closes: list,
                          window: int = 5) -> Optional[dict]:
    """Classic Head & Shoulders top pattern."""
    pivot_highs, _ = _find_pivots(highs, lows, window)
    if len(pivot_highs) < 3:
        return None

    # Try last 3 pivot highs
    for i in range(len(pivot_highs) - 1, 1, -1):
        rs_idx, rs_price = pivot_highs[i]      # right shoulder
        h_idx, h_price = pivot_highs[i - 1]    # head
        ls_idx, ls_price = pivot_highs[i - 2]  # left shoulder

        # Head must be highest
        if h_price <= ls_price or h_price <= rs_price:
            continue
        # Shoulders roughly equal
        if not _tol_equal(ls_price, rs_price, 0.03):
            continue
        # Spacing check
        if h_idx - ls_idx < window or rs_idx - h_idx < window:
            continue

        # Neckline from lows between shoulders
        nl_left = min(lows[ls_idx:h_idx + 1]) if ls_idx < h_idx else 0
        nl_right = min(lows[h_idx:rs_idx + 1]) if h_idx < rs_idx else 0
        neckline = (nl_left + nl_right) / 2
        height = h_price - neckline
        target = neckline - height

        return {
            "name": "Head & Shoulders",
            "type": "bearish",
            "strength": 3,
            "start_idx": ls_idx,
            "end_idx": rs_idx,
            "neckline": round(neckline, 4),
            "target_price": round(target, 4),
            "confidence": 0.75,
        }
    return None


def detect_inverse_head_shoulders(highs: list, lows: list, closes: list,
                                  window: int = 5) -> Optional[dict]:
    """Inverse Head & Shoulders bottom pattern."""
    _, pivot_lows = _find_pivots(highs, lows, window)
    if len(pivot_lows) < 3:
        return None

    for i in range(len(pivot_lows) - 1, 1, -1):
        rs_idx, rs_price = pivot_lows[i]
        h_idx, h_price = pivot_lows[i - 1]
        ls_idx, ls_price = pivot_lows[i - 2]

        if h_price >= ls_price or h_price >= rs_price:
            continue
        if not _tol_equal(ls_price, rs_price, 0.03):
            continue
        if h_idx - ls_idx < window or rs_idx - h_idx < window:
            continue

        nl_left = max(highs[ls_idx:h_idx + 1]) if ls_idx < h_idx else 0
        nl_right = max(highs[h_idx:rs_idx + 1]) if h_idx < rs_idx else 0
        neckline = (nl_left + nl_right) / 2
        height = neckline - h_price
        target = neckline + height

        return {
            "name": "Inverse Head & Shoulders",
            "type": "bullish",
            "strength": 3,
            "start_idx": ls_idx,
            "end_idx": rs_idx,
            "neckline": round(neckline, 4),
            "target_price": round(target, 4),
            "confidence": 0.75,
        }
    return None


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def detect_bull_flag(highs: list, lows: list, closes: list,
                     min_pole: int = 5, flag_bars: int = 10) -> Optional[dict]:
    """
    Strong rally (pole) followed by tight downward-sloping consolidation (flag).
    """
    n = len(closes)
    if n < min_pole + flag_bars:
        return None

    # Look for a strong pole: >5% gain in min_pole bars
    pole_end = n - flag_bars
    pole_start = max(0, pole_end - min_pole * 2)
    pole_gain = (closes[pole_end] - closes[pole_start]) / closes[pole_start] * 100

    if pole_gain < 5:
        return None

    # Flag: slight downward drift with narrowing range
    flag_highs = highs[pole_end:n]
    flag_lows = lows[pole_end:n]
    flag_points_h = [(i, flag_highs[i]) for i in range(len(flag_highs))]
    flag_points_l = [(i, flag_lows[i]) for i in range(len(flag_lows))]

    slope_h, _, r2_h = _linear_regression(flag_points_h)
    slope_l, _, r2_l = _linear_regression(flag_points_l)

    # Both slopes should be slightly negative, channel should be tight
    if slope_h < 0 and slope_l < 0 and r2_h > 0.5 and r2_l > 0.5:
        pole_height = closes[pole_end] - closes[pole_start]
        target = closes[-1] + pole_height
        return {
            "name": "Bull Flag",
            "type": "bullish",
            "strength": 2,
            "start_idx": pole_start,
            "end_idx": n - 1,
            "target_price": round(target, 4),
            "confidence": 0.65,
        }
    return None


def detect_bear_flag(highs: list, lows: list, closes: list,
                     min_pole: int = 5, flag_bars: int = 10) -> Optional[dict]:
    """Strong drop (pole) followed by tight upward-sloping consolidation (flag)."""
    n = len(closes)
    if n < min_pole + flag_bars:
        return None

    pole_end = n - flag_bars
    pole_start = max(0, pole_end - min_pole * 2)
    pole_loss = (closes[pole_start] - closes[pole_end]) / closes[pole_start] * 100

    if pole_loss < 5:
        return None

    flag_highs = highs[pole_end:n]
    flag_lows = lows[pole_end:n]
    flag_points_h = [(i, flag_highs[i]) for i in range(len(flag_highs))]
    flag_points_l = [(i, flag_lows[i]) for i in range(len(flag_lows))]

    slope_h, _, r2_h = _linear_regression(flag_points_h)
    slope_l, _, r2_l = _linear_regression(flag_points_l)

    if slope_h > 0 and slope_l > 0 and r2_h > 0.5 and r2_l > 0.5:
        pole_height = closes[pole_start] - closes[pole_end]
        target = closes[-1] - pole_height
        return {
            "name": "Bear Flag",
            "type": "bearish",
            "strength": 2,
            "start_idx": pole_start,
            "end_idx": n - 1,
            "target_price": round(target, 4),
            "confidence": 0.65,
        }
    return None


# ---------------------------------------------------------------------------
# Triangles
# ---------------------------------------------------------------------------

def detect_ascending_triangle(highs: list, lows: list, closes: list,
                              window: int = 5) -> Optional[dict]:
    """Flat resistance + rising support (higher lows)."""
    pivot_highs, pivot_lows = _find_pivots(highs, lows, window)
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return None

    # Check flat resistance (last 2-3 pivot highs roughly equal)
    recent_highs = pivot_highs[-3:]
    h_slope, _, _ = _linear_regression(recent_highs)
    avg_resistance = sum(p[1] for p in recent_highs) / len(recent_highs)

    # Check rising lows
    recent_lows = pivot_lows[-3:]
    l_slope, _, r2 = _linear_regression(recent_lows)

    if abs(h_slope) < 0.1 and l_slope > 0 and r2 > 0.5:
        resistance = avg_resistance
        height = resistance - recent_lows[0][1]
        target = resistance + height

        return {
            "name": "Ascending Triangle",
            "type": "bullish",
            "strength": 2,
            "start_idx": min(recent_highs[0][0], recent_lows[0][0]),
            "end_idx": max(recent_highs[-1][0], recent_lows[-1][0]),
            "resistance": round(resistance, 4),
            "target_price": round(target, 4),
            "confidence": 0.65,
        }
    return None


def detect_descending_triangle(highs: list, lows: list, closes: list,
                               window: int = 5) -> Optional[dict]:
    """Flat support + falling resistance (lower highs)."""
    pivot_highs, pivot_lows = _find_pivots(highs, lows, window)
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return None

    recent_highs = pivot_highs[-3:]
    h_slope, _, r2_h = _linear_regression(recent_highs)

    recent_lows = pivot_lows[-3:]
    l_slope, _, _ = _linear_regression(recent_lows)
    avg_support = sum(p[1] for p in recent_lows) / len(recent_lows)

    if h_slope < 0 and r2_h > 0.5 and abs(l_slope) < 0.1:
        support = avg_support
        height = recent_highs[0][1] - support
        target = support - height

        return {
            "name": "Descending Triangle",
            "type": "bearish",
            "strength": 2,
            "start_idx": min(recent_highs[0][0], recent_lows[0][0]),
            "end_idx": max(recent_highs[-1][0], recent_lows[-1][0]),
            "support": round(support, 4),
            "target_price": round(target, 4),
            "confidence": 0.65,
        }
    return None


def detect_symmetrical_triangle(highs: list, lows: list, closes: list,
                                window: int = 5) -> Optional[dict]:
    """Converging support and resistance (lower highs + higher lows)."""
    pivot_highs, pivot_lows = _find_pivots(highs, lows, window)
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return None

    recent_highs = pivot_highs[-3:]
    h_slope, _, r2_h = _linear_regression(recent_highs)

    recent_lows = pivot_lows[-3:]
    l_slope, _, r2_l = _linear_regression(recent_lows)

    if h_slope < 0 and l_slope > 0 and r2_h > 0.4 and r2_l > 0.4:
        return {
            "name": "Symmetrical Triangle",
            "type": "neutral",
            "strength": 2,
            "start_idx": min(recent_highs[0][0], recent_lows[0][0]),
            "end_idx": max(recent_highs[-1][0], recent_lows[-1][0]),
            "target_price": closes[-1],  # breakout direction unknown
            "confidence": 0.55,
        }
    return None


# ---------------------------------------------------------------------------
# Wedges
# ---------------------------------------------------------------------------

def detect_rising_wedge(highs: list, lows: list, closes: list,
                        window: int = 5) -> Optional[dict]:
    """Both highs and lows rising, but highs rising slower (converging)."""
    pivot_highs, pivot_lows = _find_pivots(highs, lows, window)
    if len(pivot_highs) < 3 or len(pivot_lows) < 3:
        return None

    recent_highs = pivot_highs[-3:]
    h_slope, _, r2_h = _linear_regression(recent_highs)

    recent_lows = pivot_lows[-3:]
    l_slope, _, r2_l = _linear_regression(recent_lows)

    if (h_slope > 0 and l_slope > 0 and l_slope > h_slope and
            r2_h > 0.5 and r2_l > 0.5):
        return {
            "name": "Rising Wedge",
            "type": "bearish",
            "strength": 2,
            "start_idx": min(recent_highs[0][0], recent_lows[0][0]),
            "end_idx": max(recent_highs[-1][0], recent_lows[-1][0]),
            "target_price": round(recent_lows[0][1], 4),
            "confidence": 0.60,
        }
    return None


def detect_falling_wedge(highs: list, lows: list, closes: list,
                         window: int = 5) -> Optional[dict]:
    """Both highs and lows falling, but lows falling slower (converging)."""
    pivot_highs, pivot_lows = _find_pivots(highs, lows, window)
    if len(pivot_highs) < 3 or len(pivot_lows) < 3:
        return None

    recent_highs = pivot_highs[-3:]
    h_slope, _, r2_h = _linear_regression(recent_highs)

    recent_lows = pivot_lows[-3:]
    l_slope, _, r2_l = _linear_regression(recent_lows)

    if (h_slope < 0 and l_slope < 0 and h_slope < l_slope and
            r2_h > 0.5 and r2_l > 0.5):
        return {
            "name": "Falling Wedge",
            "type": "bullish",
            "strength": 2,
            "start_idx": min(recent_highs[0][0], recent_lows[0][0]),
            "end_idx": max(recent_highs[-1][0], recent_lows[-1][0]),
            "target_price": round(recent_highs[0][1], 4),
            "confidence": 0.60,
        }
    return None


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def scan_chart_patterns(candles: list) -> list[dict]:
    """
    Scan candle list for all chart patterns.
    Expects Candle objects with .open, .high, .low, .close attributes.
    Returns list of pattern dicts sorted by confidence descending.
    """
    if len(candles) < 15:
        return []

    opens = [c.open for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]

    results = []

    detectors = [
        detect_double_top,
        detect_double_bottom,
        detect_head_shoulders,
        detect_inverse_head_shoulders,
        detect_ascending_triangle,
        detect_descending_triangle,
        detect_symmetrical_triangle,
        detect_rising_wedge,
        detect_falling_wedge,
    ]

    for fn in detectors:
        p = fn(highs, lows, closes)
        if p:
            results.append(p)

    # Flags need different signatures
    for fn in [detect_bull_flag, detect_bear_flag]:
        p = fn(highs, lows, closes)
        if p:
            results.append(p)

    # Sort by confidence
    results.sort(key=lambda x: -x.get("confidence", 0))
    return results


def summarize_chart_patterns(patterns: list[dict]) -> str:
    """Format chart pattern list as readable string."""
    if not patterns:
        return "No chart patterns detected"
    lines = []
    icons = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
    for p in patterns:
        icon = icons.get(p["type"], "⚪")
        conf = int(p.get("confidence", 0) * 100)
        target = p.get("target_price", 0)
        lines.append(f"{icon} {p['name']} ({p['type']}) — target ${target:.2f} ({conf}% conf)")
    return "\n".join(lines)
