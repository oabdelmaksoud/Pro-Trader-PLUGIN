"""Macro (Fundamentals) Analyst Plugin."""

from __future__ import annotations
import json
import logging
import subprocess

from pro_trader.core.interfaces import AnalystPlugin
from pro_trader.models.market_data import MarketData

logger = logging.getLogger(__name__)


class MacroAnalyst(AnalystPlugin):
    name = "macro"
    version = "1.0.0"
    description = "Fundamental/macro analysis agent"
    requires = ["fundamentals", "news"]

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

        if is_futures:
            asset_class = data.contract_spec.get("asset_class", "").upper()
            prompt = f"""You are Macro, CooperCorp Fundamentals Analyst — FUTURES MODE.
Analyze {contract_name} ({ticker}). Market data:
{data_summary}
This is a {asset_class} futures contract.
For FX futures: analyze central bank policy, rate differentials, economic data.
For commodity futures: analyze supply/demand, seasonal patterns, geopolitical risk.
For index futures: analyze equity fundamentals, VIX, sector rotation.
For crypto futures: analyze on-chain metrics, regulatory news, institutional flows.
End with: FUNDAMENTAL SCORE: X/10"""
        else:
            prompt = f"""You are Macro, CooperCorp Fundamentals Analyst.
Analyze {ticker} fundamentals. Market data:
{data_summary}
Provide: main catalyst, days to earnings, sector trend, relative P/E, insider activity, key macro risks.
End with: FUNDAMENTAL SCORE: X/10"""

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
            return result.stdout.strip() if result.returncode == 0 else f"[macro error: {result.stderr[:200]}]"
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return f"[macro: {e}]"

    @staticmethod
    def _extract_score(report: str) -> float:
        for line in report.splitlines():
            if "FUNDAMENTAL SCORE" in line.upper():
                for part in line.split():
                    try:
                        val = float(part.strip("/10").strip(":"))
                        if 0 <= val <= 10:
                            return val
                    except ValueError:
                        continue
        return 5.0
