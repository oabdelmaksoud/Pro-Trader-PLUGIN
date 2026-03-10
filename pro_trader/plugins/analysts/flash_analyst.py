"""Flash (Technical) Analyst Plugin — wraps the Flash agent."""

from __future__ import annotations
import json
import logging
import subprocess
from typing import Optional

from pro_trader.core.interfaces import AnalystPlugin
from pro_trader.models.market_data import MarketData

logger = logging.getLogger(__name__)


class FlashAnalyst(AnalystPlugin):
    name = "flash"
    version = "1.0.0"
    description = "Technical analysis agent (price action, indicators, patterns)"
    requires = ["quotes", "technicals"]

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
            prompt = f"""You are Flash, CooperCorp Technical Analyst — FUTURES MODE.
Analyze {contract_name} ({ticker}) for entry. Market data:
{data_summary}
This is a FUTURES CONTRACT. Consider: margin=${data.contract_spec.get('margin', '?')}, tick value=${data.contract_spec.get('tick_value', '?')}.
Provide: price, entry zone, stop (in ticks), target (in ticks), R:R ratio, RSI, trend direction, volume.
Futures trade nearly 24h — note session context (Globex vs RTH).
End with: TECHNICAL SCORE: X/10"""
        else:
            prompt = f"""You are Flash, CooperCorp Technical Analyst.
Analyze {ticker} for intraday entry. Market data:
{data_summary}
Provide: price, entry zone, stop (-2%), target (+6%), R:R ratio, RSI status, SMA trend, volume vs average.
End with: TECHNICAL SCORE: X/10"""

        report = self._run_llm(prompt)
        score = self._extract_score(report, "TECHNICAL SCORE")

        return {
            "report": report,
            "score": score,
            "direction": self._extract_direction(report),
            "key_points": [],
            "metadata": {"model": self._model, "futures_mode": is_futures},
        }

    def _run_llm(self, prompt: str) -> str:
        """Run LLM via claude CLI."""
        try:
            result = subprocess.run(
                ["claude", "--print", "--model", self._model, prompt],
                capture_output=True, text=True, timeout=self._timeout
            )
            return result.stdout.strip() if result.returncode == 0 else f"[flash error: {result.stderr[:200]}]"
        except FileNotFoundError:
            logger.warning("claude CLI not found — returning stub report")
            return "[flash: claude CLI not available]"
        except subprocess.TimeoutExpired:
            return "[flash: timeout]"

    @staticmethod
    def _extract_score(report: str, label: str = "TECHNICAL SCORE") -> float:
        for line in report.splitlines():
            if label in line.upper():
                for part in line.split():
                    try:
                        val = float(part.strip("/10").strip(":"))
                        if 0 <= val <= 10:
                            return val
                    except ValueError:
                        continue
        return 5.0

    @staticmethod
    def _extract_direction(report: str) -> str:
        upper = report.upper()
        if "BULLISH" in upper or "BUY" in upper:
            return "BUY"
        if "BEARISH" in upper or "SELL" in upper:
            return "SELL"
        return "HOLD"
