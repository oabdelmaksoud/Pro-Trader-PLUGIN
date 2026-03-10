"""
Pipeline Orchestrator — runs the full analysis flow using registered plugins.

Flow:
  1. Data plugins → gather MarketData
  2. Analyst plugins → produce reports (parallel)
  3. Strategy plugin → combine into Signal
  4. Risk plugins → evaluate/adjust signal
  5. Broker plugin → execute (if approved)
  6. Notifier plugins → send alerts
"""

from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from pro_trader.core.events import EventBus
from pro_trader.core.registry import PluginRegistry
from pro_trader.core.interfaces import DataPlugin, AnalystPlugin
from pro_trader.models.signal import Signal, Direction
from pro_trader.models.market_data import MarketData
from pro_trader.models.position import Portfolio

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrates the analysis pipeline using registered plugins."""

    def __init__(self, registry: PluginRegistry, bus: EventBus, config: dict):
        self.registry = registry
        self.bus = bus
        self.config = config

    def run(self, ticker: str, dry_run: bool = False,
            portfolio: Portfolio | None = None) -> Signal:
        """
        Run the full pipeline for a single ticker.

        Returns a Signal (may or may not be actionable).
        """
        self.bus.emit("pipeline.start", ticker=ticker)

        # ── Step 1: Gather data ──────────────────────────────────────
        logger.info(f"Step 1: Gathering data for {ticker}")
        data = self._gather_data(ticker)
        self.bus.emit("data.complete", ticker=ticker, data=data)

        if data.price <= 0:
            logger.warning(f"No price data for {ticker} — skipping")
            return Signal(ticker=ticker, direction=Direction.PASS, score=0.0,
                          source="pipeline", metadata={"reason": "no_price_data"})

        # ── Step 2: Run analysts ─────────────────────────────────────
        logger.info(f"Step 2: Running analysts for {ticker}")
        reports = self._run_analysts(data)
        self.bus.emit("analyst.complete", ticker=ticker, reports=reports)

        # ── Step 3: Strategy scoring ─────────────────────────────────
        logger.info(f"Step 3: Evaluating strategy for {ticker}")
        context = {
            "account_value": self.config.get("account_value", 500),
            "portfolio": portfolio,
        }
        signal = self._evaluate_strategy(data, reports, context)
        self.bus.emit("signal.new", signal=signal)

        # ── Step 4: Risk checks ──────────────────────────────────────
        logger.info(f"Step 4: Running risk checks for {ticker}")
        if portfolio is None:
            portfolio = self._get_portfolio()
        signal = self._check_risk(signal, portfolio)

        # ── Step 5: Execute (if approved and not dry run) ────────────
        if signal.is_actionable and not dry_run:
            logger.info(f"Step 5: Executing trade for {ticker}")
            self._execute(signal)
        elif signal.is_actionable and dry_run:
            logger.info(f"Step 5: DRY RUN — would execute {signal.direction.value} {ticker}")
            signal.metadata["dry_run"] = True

        # ── Step 6: Notify ───────────────────────────────────────────
        self._notify(signal)

        self.bus.emit("pipeline.complete", ticker=ticker, signal=signal)
        return signal

    def scan(self, tickers: list[str], dry_run: bool = True,
             max_workers: int = 3) -> list[Signal]:
        """Run pipeline on multiple tickers (parallel data gathering)."""
        signals = []
        portfolio = self._get_portfolio()

        for ticker in tickers:
            try:
                signal = self.run(ticker, dry_run=dry_run, portfolio=portfolio)
                signals.append(signal)
            except Exception as e:
                logger.error(f"Pipeline failed for {ticker}: {e}")
                signals.append(Signal(
                    ticker=ticker, direction=Direction.PASS, score=0.0,
                    source="pipeline", metadata={"error": str(e)}
                ))

        # Sort by score descending
        signals.sort(key=lambda s: s.score, reverse=True)
        return signals

    # ── Internal steps ───────────────────────────────────────────────

    def _gather_data(self, ticker: str) -> MarketData:
        """Collect data from all enabled DataPlugins and merge."""
        data_plugins: list[DataPlugin] = self.registry.get_plugins("data")
        merged = MarketData(ticker=ticker)

        for plugin in data_plugins:
            if not plugin.supports(ticker):
                continue
            try:
                plugin_data = plugin.get_market_data(ticker, full=True)
                # Merge: first plugin to provide a value wins
                if plugin_data.quote and not merged.quote:
                    merged.quote = plugin_data.quote
                if plugin_data.technicals and not merged.technicals:
                    merged.technicals = plugin_data.technicals
                if plugin_data.fundamentals and not merged.fundamentals:
                    merged.fundamentals = plugin_data.fundamentals
                if plugin_data.news:
                    merged.news.extend(plugin_data.news)
                if plugin_data.asset_type != "equity":
                    merged.asset_type = plugin_data.asset_type
                if plugin_data.contract_spec:
                    merged.contract_spec = plugin_data.contract_spec
                if plugin_data.futures_context:
                    merged.futures_context = plugin_data.futures_context
                # Merge raw data
                merged.raw.update(plugin_data.raw)
            except Exception as e:
                logger.warning(f"Data plugin '{plugin.name}' failed for {ticker}: {e}")

        return merged

    def _run_analysts(self, data: MarketData) -> dict[str, dict]:
        """Run all enabled AnalystPlugins in parallel."""
        analyst_plugins: list[AnalystPlugin] = self.registry.get_plugins("analyst")
        reports = {}

        with ThreadPoolExecutor(max_workers=len(analyst_plugins) or 1) as ex:
            futures = {
                ex.submit(self._safe_analyze, plugin, data): plugin.name
                for plugin in analyst_plugins
            }
            for future in as_completed(futures, timeout=120):
                name = futures[future]
                try:
                    reports[name] = future.result(timeout=120)
                except Exception as e:
                    reports[name] = {"report": f"[{name} error: {e}]", "score": 0}

        return reports

    @staticmethod
    def _safe_analyze(plugin: AnalystPlugin, data: MarketData) -> dict:
        """Wrapper to catch analyst exceptions."""
        try:
            return plugin.analyze(data)
        except Exception as e:
            return {"report": f"[{plugin.name} error: {e}]", "score": 0}

    def _evaluate_strategy(self, data: MarketData, reports: dict,
                           context: dict) -> Signal:
        """Run the first enabled StrategyPlugin."""
        strategy_plugins = self.registry.get_plugins("strategy")
        if not strategy_plugins:
            # Fallback: build signal from data score
            return Signal(
                ticker=data.ticker,
                direction=Direction.HOLD,
                score=data.score,
                price=data.price,
                asset_type=data.asset_type,
                analyst_reports=reports,
                source="fallback",
            )

        strategy = strategy_plugins[0]
        return strategy.evaluate(data, reports, context)

    def _check_risk(self, signal: Signal, portfolio: Portfolio) -> Signal:
        """Run all enabled RiskPlugins. Any rejection blocks the trade."""
        risk_plugins = self.registry.get_plugins("risk")

        for plugin in risk_plugins:
            try:
                verdict = plugin.evaluate(signal, portfolio)
                if not verdict.get("approved", True):
                    signal.direction = Direction.PASS
                    signal.metadata["risk_rejected_by"] = plugin.name
                    signal.metadata["risk_reason"] = verdict.get("reason", "")
                    self.bus.emit("signal.rejected", signal=signal, verdict=verdict)
                    return signal

                # Apply adjustments (e.g., position sizing)
                adjustments = verdict.get("adjustments", {})
                if "position_size" in adjustments:
                    signal.position_size = adjustments["position_size"]

                # Collect warnings
                for warning in verdict.get("warnings", []):
                    signal.intelligence_bonuses.append(f"RISK: {warning}")

            except Exception as e:
                logger.warning(f"Risk plugin '{plugin.name}' failed: {e}")

        self.bus.emit("signal.approved", signal=signal)
        return signal

    def _execute(self, signal: Signal) -> None:
        """Execute trade via the first enabled BrokerPlugin."""
        broker_plugins = self.registry.get_plugins("broker")
        if not broker_plugins:
            logger.warning("No broker plugin available — skipping execution")
            return

        from pro_trader.models.position import Order, OrderSide, OrderType
        order = Order(
            symbol=signal.ticker,
            side=OrderSide.BUY if signal.direction == Direction.BUY else OrderSide.SELL,
            qty=signal.position_size or 1,
            order_type=OrderType.BRACKET if signal.stop_loss else OrderType.MARKET,
            stop_price=signal.stop_loss,
            take_profit=signal.take_profit,
        )

        broker = broker_plugins[0]
        result = broker.submit_order(order)
        signal.metadata["order_result"] = {
            "success": result.success,
            "order_id": result.order_id,
            "status": result.status,
            "message": result.message,
        }
        self.bus.emit("order.submitted", order=order, result=result)

    def _notify(self, signal: Signal) -> None:
        """Send signal to all enabled NotifierPlugins."""
        notifier_plugins = self.registry.get_plugins("notifier")
        for plugin in notifier_plugins:
            try:
                plugin.notify(signal)
            except Exception as e:
                logger.warning(f"Notifier '{plugin.name}' failed: {e}")

    def _get_portfolio(self) -> Portfolio:
        """Get portfolio from broker, or return empty."""
        broker_plugins = self.registry.get_plugins("broker")
        if broker_plugins:
            try:
                return broker_plugins[0].get_portfolio()
            except Exception as e:
                logger.warning(f"Failed to get portfolio: {e}")
        return Portfolio(cash=self.config.get("account_value", 500))
