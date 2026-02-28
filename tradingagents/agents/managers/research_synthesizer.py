#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Research Manager Synthesis (Gap 3)
Mirrors the upstream Research Manager role:
Takes reports from Flash (technical), Macro (fundamentals), Pulse (sentiment/news)
and synthesizes them into a unified briefing before the Bull/Bear debate.

Also injects BM25 memory context from similar past situations (Gap 1).

Usage (called by scan pipeline):
  from tradingagents.agents.managers.research_synthesizer import synthesize_research
  briefing = synthesize_research(ticker, flash_report, macro_report, pulse_report)
"""
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO))


def synthesize_research(
    ticker: str,
    flash_report: str,
    macro_report: str,
    pulse_report: str,
    score: float = 0.0,
    price: float = 0.0,
) -> str:
    """
    Synthesize three analyst reports into a unified research briefing.
    Injects BM25 memory of similar past situations.
    Returns a formatted briefing string for Bull/Bear agents.
    """
    # Pull BM25 similar situations
    memory_context = ""
    try:
        from tradingagents.memory import get_memory
        memory = get_memory()
        query = f"{ticker} {flash_report[:200]} {macro_report[:200]} {pulse_report[:200]}"
        memory_context = memory.format_for_prompt(query, top_k=3)
    except Exception as e:
        memory_context = f"Memory unavailable: {e}"

    briefing = f"""# Research Briefing — {ticker}
**Pre-score:** {score:.1f}/10 | **Current price:** ${price:.2f}

---

## 📈 Technical Analysis (Flash)
{flash_report}

---

## 🌍 Fundamental & Macro Analysis (Macro)
{macro_report}

---

## 💬 Sentiment & News Analysis (Pulse)
{pulse_report}

---

## 🧠 BM25 Memory — Similar Past Situations
{memory_context}

---

## Research Manager Summary
Based on the above three analyst reports, key points for Bull/Bear debate:
- Technical setup: {_extract_signal(flash_report, 'technical')}
- Macro headwinds/tailwinds: {_extract_signal(macro_report, 'macro')}
- Sentiment bias: {_extract_signal(pulse_report, 'sentiment')}
- Historical precedent: {'Available — see BM25 above' if 'Relevant past' in memory_context else 'No similar situations in memory yet'}

Proceed to structured Bull/Bear debate with this full context.
"""
    return briefing


def _extract_signal(report: str, kind: str) -> str:
    """Extract a brief signal from a report."""
    if not report:
        return "N/A"
    # Take first sentence that contains a signal word
    signal_words = {
        "technical": ["bullish", "bearish", "oversold", "overbought", "breakout", "breakdown", "support", "resistance"],
        "macro": ["growth", "inflation", "recession", "rate", "dovish", "hawkish", "expansion", "contraction"],
        "sentiment": ["positive", "negative", "fear", "greed", "bullish", "bearish", "buzz", "trending"],
    }
    words = signal_words.get(kind, [])
    for sentence in report.replace("\n", " ").split("."):
        if any(w in sentence.lower() for w in words):
            return sentence.strip()[:120]
    return report[:100].strip()
