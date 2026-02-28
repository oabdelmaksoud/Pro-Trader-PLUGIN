#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Multi-Round Debate Engine (Gap 4)
Mirrors upstream max_debate_rounds config.
Runs Bull vs Bear for N rounds, each round building on the prior,
until convergence or max rounds reached.

Bull/Bear are run via OpenClaw sessions_spawn (no direct API key needed).
"""
import json
import re
from typing import Tuple


def run_debate(
    ticker: str,
    briefing: str,
    bull_report: str,
    bear_report: str,
    max_rounds: int = 2,
) -> Tuple[str, str, float]:
    """
    Run multi-round Bull/Bear debate.
    Returns: (final_bull_position, final_bear_position, conviction_delta)
    conviction_delta > 0 means bull won, < 0 means bear won.
    """
    if max_rounds <= 1:
        return bull_report, bear_report, _score_debate(bull_report, bear_report)

    # For rounds 2+, each side rebuts the other's prior argument
    current_bull = bull_report
    current_bear = bear_report

    for round_num in range(2, max_rounds + 1):
        # Bull rebuttal to Bear
        bull_rebuttal_prompt = f"""You are Bull 🐂 on {ticker}. You previously argued:
{current_bull[:500]}

Bear argued:
{current_bear[:500]}

Round {round_num} — REBUTTAL: Address Bear's strongest points. Strengthen your bull case.
Be specific. Keep to 200 words. Conclude with: CONVICTION: [1-10]"""

        # Bear rebuttal to Bull
        bear_rebuttal_prompt = f"""You are Bear 🐻 on {ticker}. You previously argued:
{current_bear[:500]}

Bull argued:
{current_bull[:500]}

Round {round_num} — REBUTTAL: Address Bull's strongest points. Strengthen your bear case.
Be specific. Keep to 200 words. Conclude with: CONVICTION: [1-10]"""

        # Run both via openclaw CLI (quick, non-blocking)
        import subprocess, sys
        from pathlib import Path
        REPO = Path(__file__).resolve().parent.parent.parent

        try:
            bull_result = subprocess.run(
                ["claude", "--print", "--model", "claude-opus-4-6", bull_rebuttal_prompt],
                capture_output=True, text=True, timeout=60, cwd=str(REPO)
            )
            if bull_result.returncode == 0 and bull_result.stdout.strip():
                current_bull = bull_result.stdout.strip()
        except Exception as e:
            print(f"Bull round {round_num} failed: {e}")

        try:
            bear_result = subprocess.run(
                ["claude", "--print", "--model", "claude-opus-4-6", bear_rebuttal_prompt],
                capture_output=True, text=True, timeout=60, cwd=str(REPO)
            )
            if bear_result.returncode == 0 and bear_result.stdout.strip():
                current_bear = bear_result.stdout.strip()
        except Exception as e:
            print(f"Bear round {round_num} failed: {e}")

    conviction_delta = _score_debate(current_bull, current_bear)
    return current_bull, current_bear, conviction_delta


def _score_debate(bull: str, bear: str) -> float:
    """
    Extract CONVICTION scores and compute delta (positive = bull stronger).
    """
    def extract_conviction(text: str) -> float:
        patterns = [
            r"CONVICTION[:\s]+(\d+(?:\.\d+)?)",
            r"conviction[:\s]+(\d+(?:\.\d+)?)",
            r"(\d+(?:\.\d+)?)\s*/\s*10",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                return float(m.group(1))
        # Heuristic: count bullish vs bearish signal words
        bull_words = len(re.findall(r'\b(strong|upside|breakout|buy|long|bullish|growth|rally)\b', text, re.I))
        bear_words = len(re.findall(r'\b(weak|downside|breakdown|sell|short|bearish|decline|drop)\b', text, re.I))
        return 5.0 + (bull_words - bear_words) * 0.2

    bull_conv = extract_conviction(bull)
    bear_conv = extract_conviction(bear)
    return bull_conv - bear_conv  # positive = bull stronger


def format_debate_summary(
    ticker: str,
    bull_final: str,
    bear_final: str,
    conviction_delta: float,
    rounds: int,
) -> str:
    """Format debate outcome for Risk Manager."""
    bias = "BULLISH" if conviction_delta > 1 else "BEARISH" if conviction_delta < -1 else "NEUTRAL"
    return f"""## Bull/Bear Debate Summary — {ticker} ({rounds} round{'s' if rounds > 1 else ''})

**Debate outcome:** {bias} (delta={conviction_delta:+.1f})

### 🐂 Bull Final Position
{bull_final[:600]}

### 🐻 Bear Final Position
{bear_final[:600]}

### Synthesis
The debate {'favors bulls' if conviction_delta > 0 else 'favors bears' if conviction_delta < 0 else 'is inconclusive'} with a delta of {conviction_delta:+.1f}.
{'Entry conviction is reinforced.' if conviction_delta > 1 else 'Entry conviction is weakened — consider raising threshold.' if conviction_delta < -1 else 'Mixed signals — apply standard threshold.'}
"""
