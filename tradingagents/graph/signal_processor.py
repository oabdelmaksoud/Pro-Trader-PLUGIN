#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Signal Processing Layer (Gap 5)
Structured extraction of trade signals from agent outputs.
Converts free-text agent reports into a normalized signal dict
that feeds into trade_gate.py with consistent structure.

Mirrors upstream signal_processing.py but integrated with our pipeline.
"""
import re
import json
from typing import Optional


def extract_signal(
    ticker: str,
    flash_report: str = "",
    macro_report: str = "",
    pulse_report: str = "",
    risk_report: str = "",
    debate_summary: str = "",
    raw_score: float = 0.0,
    conviction_delta: float = 0.0,
) -> dict:
    """
    Extract a normalized signal dict from all agent reports.
    Returns a dict compatible with trade_gate.py input.
    """
    direction = _extract_direction(flash_report + debate_summary + risk_report)
    confidence = _extract_confidence(risk_report + debate_summary)
    price_target = _extract_price_target(flash_report + risk_report)
    stop_loss = _extract_stop_loss(risk_report)
    catalysts = _extract_catalysts(macro_report + pulse_report)
    risks = _extract_risks(risk_report + debate_summary)

    # Adjust score based on debate outcome
    adjusted_score = raw_score
    if conviction_delta > 2:
        adjusted_score += 0.3
    elif conviction_delta < -2:
        adjusted_score -= 0.3
    adjusted_score = max(0.0, min(10.0, adjusted_score))

    signal = {
        "ticker": ticker,
        "direction": direction,
        "score": round(adjusted_score, 2),
        "confidence": confidence,
        "price_target": price_target,
        "stop_loss": stop_loss,
        "catalysts": catalysts[:3],
        "risks": risks[:3],
        "debate_bias": "bull" if conviction_delta > 0 else "bear" if conviction_delta < 0 else "neutral",
        "conviction_delta": round(conviction_delta, 2),
        "signal_source": "full_pipeline",
    }
    return signal


def _extract_direction(text: str) -> str:
    """Extract BUY/SELL/HOLD direction from agent text."""
    text_lower = text.lower()
    buy_patterns = [r'\bbuy\b', r'\blong\b', r'\bbullish\b', r'recommend.*buy', r'enter.*long']
    sell_patterns = [r'\bsell\b', r'\bshort\b', r'\bbearish\b', r'recommend.*sell', r'enter.*short']
    hold_patterns = [r'\bhold\b', r'\bwait\b', r'\bneutral\b', r'\bsidelined\b']

    buy_count = sum(len(re.findall(p, text_lower)) for p in buy_patterns)
    sell_count = sum(len(re.findall(p, text_lower)) for p in sell_patterns)
    hold_count = sum(len(re.findall(p, text_lower)) for p in hold_patterns)

    if buy_count > sell_count and buy_count > hold_count:
        return "BUY"
    elif sell_count > buy_count and sell_count > hold_count:
        return "SELL"
    return "HOLD"


def _extract_confidence(text: str) -> int:
    """Extract confidence/conviction score 1-10."""
    patterns = [
        r'confidence[:\s]+(\d+)',
        r'conviction[:\s]+(\d+)',
        r'CONVICTION[:\s]+(\d+)',
        r'(\d+)\s*/\s*10',
        r'(\d+)%\s+confident',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = int(m.group(1))
            if val > 10:
                val = val // 10  # percentage → 1-10
            return max(1, min(10, val))
    return 5  # default


def _extract_price_target(text: str) -> Optional[float]:
    """Extract price target from text."""
    patterns = [
        r'(?:price target|PT|target price)[:\s]+\$?(\d+(?:\.\d+)?)',
        r'target[:\s]+\$(\d+(?:\.\d+)?)',
        r'\$(\d+(?:\.\d+)?)\s+(?:target|PT)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def _extract_stop_loss(text: str) -> Optional[float]:
    """Extract stop loss from text."""
    patterns = [
        r'(?:stop loss|stop|SL)[:\s]+\$?(\d+(?:\.\d+)?)',
        r'stop at \$?(\d+(?:\.\d+)?)',
        r'\$(\d+(?:\.\d+)?)\s+stop',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def _extract_catalysts(text: str) -> list:
    """Extract key bullish catalysts."""
    catalysts = []
    patterns = [
        r'(?:catalyst|driver|tailwind)[:\s]+([^.\n]{10,80})',
        r'(?:earnings|FDA|acquisition|contract|guidance)[^.\n]{5,60}',
    ]
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            c = m.group(0 if '(' not in p else 1).strip()
            if len(c) > 10:
                catalysts.append(c[:80])
    return list(dict.fromkeys(catalysts))  # dedupe preserving order


def _extract_risks(text: str) -> list:
    """Extract key risks."""
    risks = []
    patterns = [
        r'(?:risk|headwind|concern|warning)[:\s]+([^.\n]{10,80})',
        r'(?:downside|bearish|weakness)[^.\n]{5,60}',
    ]
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            r = m.group(0 if '(' not in p else 1).strip()
            if len(r) > 10:
                risks.append(r[:80])
    return list(dict.fromkeys(risks))


def format_signal_card(signal: dict) -> str:
    """Format signal for display/logging."""
    direction_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(signal.get("direction", "HOLD"), "⚪")
    lines = [
        f"{direction_emoji} **Signal: {signal.get('direction', 'HOLD')}** | Score: {signal.get('score', 0):.1f} | Confidence: {signal.get('confidence', 5)}/10",
        f"Debate bias: {signal.get('debate_bias', 'neutral').upper()} (Δ{signal.get('conviction_delta', 0):+.1f})",
    ]
    if signal.get("price_target"):
        lines.append(f"Target: ${signal['price_target']:.2f}")
    if signal.get("catalysts"):
        lines.append(f"Catalysts: {' | '.join(signal['catalysts'][:2])}")
    if signal.get("risks"):
        lines.append(f"Risks: {' | '.join(signal['risks'][:2])}")
    return "\n".join(lines)
