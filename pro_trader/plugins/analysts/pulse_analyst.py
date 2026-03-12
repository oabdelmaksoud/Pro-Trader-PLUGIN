"""Pulse (Sentiment) Analyst Plugin."""

from __future__ import annotations
import json
import logging
import subprocess

from pro_trader.core.interfaces import AnalystPlugin
from pro_trader.models.market_data import MarketData

from pro_trader.plugins.analysts.flash_analyst import _build_profile_block

logger = logging.getLogger(__name__)


class PulseAnalyst(AnalystPlugin):
    name = "pulse"
    version = "1.0.0"
    description = "Sentiment and options flow analysis agent"
    requires = ["news"]

    def __init__(self):
        self._model = "claude-sonnet-4-6"
        self._timeout = 90

    def configure(self, config: dict) -> None:
        self._model = config.get("model", self._model)
        self._timeout = config.get("timeout", self._timeout)

    def analyze(self, data: MarketData, context: dict | None = None) -> dict:
        is_futures = data.asset_type == "futures"
        ticker = data.ticker
        contract_name = data.contract_spec.get("name", ticker) if is_futures else ticker
        data_summary = json.dumps(data.to_dict(), indent=2, default=str)[:1500]
        profile_block = _build_profile_block(context)

        if is_futures:
            prompt = f"""You are Pulse, CooperCorp Sentiment Analyst — FUTURES MODE.
{profile_block}
Analyze {contract_name} ({ticker}) sentiment. Market data:
{data_summary}
This is a futures contract — consider: COT (Commitment of Traders) positioning,
institutional vs retail sentiment, open interest trends, funding rates (crypto).
Check for geopolitical risk events affecting this asset class.
End with: SENTIMENT SCORE: X/10"""
        else:
            prompt = f"""You are Pulse, CooperCorp Sentiment & Options Analyst.
{profile_block}
Analyze {ticker} sentiment. Market data:
{data_summary}
Provide: news tone, options PCR, unusual options activity, Reddit/social buzz, dark pool signals, fear/greed.
End with: SENTIMENT SCORE: X/10"""

        report = self._run_llm(prompt)
        score = self._extract_score(report)

        return {
            "report": report,
            "score": score,
            "direction": "HOLD",
            "key_points": [],
            "metadata": {"model": self._model, "futures_mode": is_futures},
        }

    def _run_llm(self, prompt: str) -> str:
        try:
            result = subprocess.run(
                ["claude", "--print", "--model", self._model, prompt],
                capture_output=True, text=True, timeout=self._timeout
            )
            return result.stdout.strip() if result.returncode == 0 else f"[pulse error: {result.stderr[:200]}]"
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return f"[pulse: {e}]"

    @staticmethod
    def _extract_score(report: str) -> float:
        for line in report.splitlines():
            if "SENTIMENT SCORE" in line.upper():
                for part in line.split():
                    try:
                        val = float(part.strip("/10").strip(":"))
                        if 0 <= val <= 10:
                            return val
                    except ValueError:
                        continue
        return 5.0
