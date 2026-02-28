#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Persistent BM25 Situation Memory
Extends FinancialSituationMemory with JSON persistence so agents
can learn from past similar market situations across sessions.

Stores: (situation_text, recommendation, outcome, pnl_pct, ticker)
Retrieves: top-K similar past situations using BM25
"""
import json
import re
import time
from pathlib import Path
from typing import List, Tuple, Optional
from rank_bm25 import BM25Okapi

REPO = Path(__file__).resolve().parent.parent.parent
MEMORY_FILE = REPO / "logs" / "situation_memory.json"
MAX_MEMORIES = 500  # prune oldest beyond this


class PersistentSituationMemory:
    """BM25-powered financial situation memory with JSON persistence."""

    def __init__(self, name: str = "global"):
        self.name = name
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        try:
            if MEMORY_FILE.exists():
                data = json.loads(MEMORY_FILE.read_text())
                self.memories = data.get("memories", [])
            else:
                self.memories = []
        except Exception:
            self.memories = []
        self._rebuild_index()

    def _save(self):
        try:
            MEMORY_FILE.write_text(json.dumps({"memories": self.memories}, indent=2))
        except Exception:
            pass

    def _rebuild_index(self):
        self.documents = [m["situation"] for m in self.memories]
        if self.documents:
            tokenized = [self._tokenize(d) for d in self.documents]
            self.bm25 = BM25Okapi(tokenized)
        else:
            self.bm25 = None

    # ── Core ops ─────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r'\b\w+\b', text.lower())

    def add_situation(
        self,
        situation: str,
        recommendation: str,
        ticker: str = "",
        pnl_pct: float = 0.0,
        outcome: str = "",  # win|loss|neutral
    ):
        """Store a new market situation and what we did."""
        self.memories.append({
            "situation": situation,
            "recommendation": recommendation,
            "ticker": ticker,
            "pnl_pct": pnl_pct,
            "outcome": outcome,
            "timestamp": time.time(),
        })
        # Prune oldest if over limit
        if len(self.memories) > MAX_MEMORIES:
            self.memories = self.memories[-MAX_MEMORIES:]
        self._save()
        self._rebuild_index()

    def get_similar_situations(
        self, query: str, top_k: int = 3
    ) -> List[Tuple[str, str, float]]:
        """Return top-K similar situations as (situation, recommendation, pnl_pct)."""
        if not self.bm25 or not self.memories:
            return []
        tokens = self._tokenize(query)
        scores = self.bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        results = []
        for i in top_indices:
            if scores[i] > 0:
                m = self.memories[i]
                results.append((m["situation"], m["recommendation"], m.get("pnl_pct", 0.0)))
        return results

    def format_for_prompt(self, query: str, top_k: int = 3) -> str:
        """Format similar past situations for injection into an agent prompt."""
        similar = self.get_similar_situations(query, top_k)
        if not similar:
            return "No similar past situations found in memory."
        lines = ["**Relevant past situations (BM25 retrieval):**"]
        for i, (sit, rec, pnl) in enumerate(similar, 1):
            outcome_str = f"+{pnl:.1f}%" if pnl > 0 else f"{pnl:.1f}%"
            lines.append(f"{i}. Situation: {sit[:200]}")
            lines.append(f"   Recommendation: {rec[:100]} | Outcome: {outcome_str}")
        return "\n".join(lines)

    def stats(self) -> dict:
        wins = [m for m in self.memories if m.get("outcome") == "win"]
        losses = [m for m in self.memories if m.get("outcome") == "loss"]
        return {
            "total": len(self.memories),
            "wins": len(wins),
            "losses": len(losses),
            "avg_win_pnl": sum(m["pnl_pct"] for m in wins) / len(wins) if wins else 0,
            "avg_loss_pnl": sum(m["pnl_pct"] for m in losses) / len(losses) if losses else 0,
        }


# Singleton
_memory = None

def get_memory() -> PersistentSituationMemory:
    global _memory
    if _memory is None:
        _memory = PersistentSituationMemory()
    return _memory


if __name__ == "__main__":
    mem = get_memory()
    print("Memory stats:", mem.stats())
    # Example query
    result = mem.format_for_prompt("NVDA high RSI overbought earnings beat oil spike")
    print(result)
