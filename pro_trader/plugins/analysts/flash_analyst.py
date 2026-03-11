"""Flash (Technical) Analyst Plugin — wraps the Flash agent."""

from __future__ import annotations
import json
import logging
import subprocess
from typing import Optional

from pro_trader.core.interfaces import AnalystPlugin
from pro_trader.models.market_data import MarketData

logger = logging.getLogger(__name__)


def _build_profile_block(context: dict | None) -> str:
    """Build a prompt section from the trader profile so AI personalizes advice."""
    if not context:
        return ""
    profile = context.get("trader_profile", {})
    if not profile:
        return ""

    parts = []
    parts.append("TRADER CONTEXT (personalize your analysis to this trader):")

    acct = profile.get("account_size")
    if acct:
        parts.append(f"- Account size: ${acct:,.0f}")

    risk = profile.get("risk_tolerance")
    if risk:
        parts.append(f"- Risk tolerance: {risk}")

    style = profile.get("trading_style")
    period = profile.get("holding_period")
    if style:
        parts.append(f"- Trading style: {style} (holding: {period or 'days'})")

    exp = profile.get("experience_level")
    if exp:
        parts.append(f"- Experience: {exp}")

    goal = profile.get("trading_goal")
    if goal:
        parts.append(f"- Goal: {goal}")

    max_risk = profile.get("max_loss_per_trade_pct")
    if max_risk:
        parts.append(f"- Max risk per trade: {max_risk}%")

    if profile.get("recovery_mode"):
        loss = profile.get("losses_to_recover", 0)
        strategy = profile.get("recovery_strategy", "moderate")
        timeline = profile.get("recovery_timeline_weeks")
        parts.append(f"- RECOVERY MODE: recovering ${loss:,.0f}, strategy={strategy}")
        if timeline:
            parts.append(f"- Recovery timeline: {timeline} weeks")
        parts.append("- Prioritize high-probability setups. Avoid speculation.")

    if len(parts) <= 1:
        return ""
    return "\n".join(parts)


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
        profile_block = _build_profile_block(context)

        if is_futures:
            prompt = f"""You are Flash, CooperCorp Technical Analyst — FUTURES MODE.
{profile_block}
Analyze {contract_name} ({ticker}) for entry. Market data:
{data_summary}
This is a FUTURES CONTRACT. Consider: margin=${data.contract_spec.get('margin', '?')}, tick value=${data.contract_spec.get('tick_value', '?')}.
Provide: price, entry zone, stop (in ticks), target (in ticks), R:R ratio, RSI, trend direction, volume.
Futures trade nearly 24h — note session context (Globex vs RTH).
End with: TECHNICAL SCORE: X/10"""
        else:
            prompt = f"""You are Flash, CooperCorp Technical Analyst.
{profile_block}
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
