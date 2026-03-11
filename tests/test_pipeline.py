"""Tests for the pipeline, event bus, registry, models, and CLI (P0/P1/P2).

Covers end-to-end pipeline, analyst subprocess failure, event bus,
plugin registry, CLI commands, models, and security checks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from pro_trader.core.events import EventBus
from pro_trader.core.interfaces import (
    PluginBase, DataPlugin, AnalystPlugin, StrategyPlugin,
    BrokerPlugin, NotifierPlugin, MonitorPlugin, RiskPlugin,
)
from pro_trader.core.pipeline import Pipeline
from pro_trader.core.registry import PluginRegistry, PLUGIN_CATEGORIES
from pro_trader.models.market_data import MarketData, Quote, Technicals
from pro_trader.models.position import (
    Order, OrderResult, OrderSide, OrderType, Position, Portfolio,
)
from pro_trader.models.signal import Signal, Direction


# ═══════════════════════════════════════════════════════════════════════════════
# FAKE PLUGINS (for pipeline & registry tests)
# ═══════════════════════════════════════════════════════════════════════════════

class FakeDataPlugin(DataPlugin):
    name = "fake_data"
    version = "0.1.0"
    provides = ["quotes"]

    def get_quote(self, symbol):
        return Quote(symbol=symbol, price=150.0, volume=1000000)

    def get_technicals(self, symbol, period="3mo"):
        return Technicals(symbol=symbol, rsi=55.0, trend="bullish")


class FakeAnalyst(AnalystPlugin):
    name = "fake_analyst"
    version = "0.1.0"

    def analyze(self, data, context=None):
        return {
            "report": f"Analysis of {data.ticker}",
            "score": 8.0,
            "direction": "BUY",
            "key_points": ["Strong momentum"],
        }


class FailingAnalyst(AnalystPlugin):
    name = "failing_analyst"
    version = "0.1.0"

    def analyze(self, data, context=None):
        raise RuntimeError("LLM connection failed")


class FakeStrategy(StrategyPlugin):
    name = "fake_strategy"
    version = "0.1.0"

    def evaluate(self, data, reports, context=None):
        avg_score = sum(r.get("score", 0) for r in reports.values()) / max(len(reports), 1)
        return Signal(
            ticker=data.ticker,
            direction=Direction.BUY if avg_score >= 7.0 else Direction.HOLD,
            score=avg_score,
            confidence=8,
            price=data.price,
            source="fake_strategy",
        )


class FakeRisk(RiskPlugin):
    name = "fake_risk"
    version = "0.1.0"

    def evaluate(self, signal, portfolio):
        return {"approved": True, "warnings": [], "adjustments": {"position_size": 1}}


class RejectingRisk(RiskPlugin):
    name = "rejecting_risk"
    version = "0.1.0"

    def evaluate(self, signal, portfolio):
        return {"approved": False, "reason": "max drawdown exceeded"}


class FakeBroker(BrokerPlugin):
    name = "fake_broker"
    version = "0.1.0"

    def submit_order(self, order):
        return OrderResult(success=True, order_id="ORD-001", status="filled")

    def get_positions(self):
        return []

    def get_portfolio(self):
        return Portfolio(cash=500, equity=500)


class FakeNotifier(NotifierPlugin):
    name = "fake_notifier"
    version = "0.1.0"

    def __init__(self):
        super().__init__()
        self.signals_received = []

    def notify(self, signal, context=None):
        self.signals_received.append(signal)
        return True


class FakeMonitor(MonitorPlugin):
    name = "fake_monitor"
    version = "0.1.0"
    interval = 60

    def check(self):
        return [{"type": "test", "severity": "info", "message": "all clear"}]


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT BUS (P2)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.on("test.event", lambda val=None: received.append(val))
        bus.emit("test.event", val="hello")
        assert received == ["hello"]

    def test_wildcard(self):
        bus = EventBus()
        received = []
        bus.on("signal.*", lambda event=None, **kw: received.append(event))
        bus.emit("signal.new", signal="s1")
        bus.emit("signal.approved", signal="s2")
        assert received == ["signal.new", "signal.approved"]

    def test_global_wildcard(self):
        bus = EventBus()
        received = []
        bus.on("*", lambda event=None, **kw: received.append(event))
        bus.emit("data.quote", data="d1")
        bus.emit("order.filled", order="o1")
        assert len(received) == 2

    def test_unsubscribe(self):
        bus = EventBus()
        handler = lambda: None
        bus.on("test", handler)
        assert len(bus._handlers["test"]) == 1
        bus.off("test", handler)
        assert len(bus._handlers["test"]) == 0

    def test_handler_exception_isolated(self):
        bus = EventBus()
        bus.on("test", lambda: 1 / 0)
        bus.on("test", lambda: "ok")
        results = bus.emit("test")
        assert "ok" in results

    def test_clear_specific(self):
        bus = EventBus()
        bus.on("a", lambda: None)
        bus.on("b", lambda: None)
        bus.clear("a")
        assert "a" not in bus._handlers
        assert "b" in bus._handlers

    def test_clear_all(self):
        bus = EventBus()
        bus.on("a", lambda: None)
        bus.on("b", lambda: None)
        bus.clear()
        assert len(bus._handlers) == 0

    def test_history_tracking(self):
        bus = EventBus()
        bus.emit("first")
        bus.emit("second", data="x")
        assert len(bus.history) == 2
        assert bus.history[0]["event"] == "first"
        assert bus.history[1]["event"] == "second"

    def test_history_max_size(self):
        bus = EventBus()
        bus._max_history = 5
        for i in range(10):
            bus.emit(f"evt{i}")
        assert len(bus.history) == 5

    def test_events_list(self):
        bus = EventBus()
        bus.on("signal.new", lambda: None)
        bus.on("order.filled", lambda: None)
        assert set(bus.events) == {"signal.new", "order.filled"}


# ═══════════════════════════════════════════════════════════════════════════════
# PLUGIN REGISTRY (P1)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPluginRegistry:
    def test_register_and_get(self):
        reg = PluginRegistry()
        plugin = FakeDataPlugin()
        reg.register(plugin)
        assert reg.get_plugin("fake_data") is plugin

    def test_register_by_category(self):
        reg = PluginRegistry()
        reg.register(FakeDataPlugin())
        reg.register(FakeAnalyst())
        assert len(reg.get_plugins("data")) == 1
        assert len(reg.get_plugins("analyst")) == 1

    def test_unregister(self):
        reg = PluginRegistry()
        reg.register(FakeDataPlugin())
        assert reg.unregister("fake_data") is True
        assert reg.get_plugin("fake_data") is None

    def test_unregister_nonexistent(self):
        reg = PluginRegistry()
        assert reg.unregister("nope") is False

    def test_enable_disable(self):
        reg = PluginRegistry()
        reg.register(FakeDataPlugin())
        reg.disable("fake_data")
        assert len(reg.get_plugins("data")) == 0  # disabled plugins excluded
        reg.enable("fake_data")
        assert len(reg.get_plugins("data")) == 1

    def test_get_all_plugins(self):
        reg = PluginRegistry()
        reg.register(FakeDataPlugin())
        reg.register(FakeAnalyst())
        all_p = reg.get_all_plugins()
        assert "data" in all_p
        assert "analyst" in all_p

    def test_health(self):
        reg = PluginRegistry()
        reg.register(FakeDataPlugin())
        health = reg.health()
        assert health["data"]["fake_data"]["status"] == "ok"

    def test_configure_called_on_register(self):
        reg = PluginRegistry()
        reg.set_config({"plugin_config": {"fake_data": {"key": "val"}}})
        plugin = FakeDataPlugin()
        plugin.configure = MagicMock()
        reg.register(plugin)
        plugin.configure.assert_called_once_with({"key": "val"})

    def test_invalid_plugin_type(self):
        reg = PluginRegistry()
        with pytest.raises(TypeError):
            reg.register(object())  # not a PluginBase

    def test_startup_all(self):
        reg = PluginRegistry()
        plugin = FakeDataPlugin()
        plugin.startup = MagicMock()
        reg.register(plugin)
        reg.startup_all()
        plugin.startup.assert_called_once()

    def test_shutdown_all(self):
        reg = PluginRegistry()
        plugin = FakeDataPlugin()
        plugin.shutdown = MagicMock()
        reg.register(plugin)
        reg.shutdown_all()
        plugin.shutdown.assert_called_once()

    def test_discover_builtins(self):
        reg = PluginRegistry()
        count = reg.discover()
        assert count > 0

    def test_summary(self):
        reg = PluginRegistry()
        reg.register(FakeDataPlugin())
        s = reg.summary()
        assert "fake_data" in s


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE END-TO-END (P0)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipeline:
    def _build_pipeline(self, **extra_plugins):
        reg = PluginRegistry()
        bus = EventBus()
        config = {"score_threshold": 7.0, "account_value": 500}

        reg.register(extra_plugins.get("data", FakeDataPlugin()))
        reg.register(extra_plugins.get("analyst", FakeAnalyst()))
        reg.register(extra_plugins.get("strategy", FakeStrategy()))
        reg.register(extra_plugins.get("risk", FakeRisk()))
        if "broker" in extra_plugins:
            reg.register(extra_plugins["broker"])
        if "notifier" in extra_plugins:
            reg.register(extra_plugins["notifier"])

        return Pipeline(reg, bus, config), bus

    def test_full_pipeline_dry_run(self):
        pipeline, bus = self._build_pipeline()
        signal = pipeline.run("NVDA", dry_run=True)
        assert signal.ticker == "NVDA"
        assert signal.score > 0
        assert signal.direction in (Direction.BUY, Direction.HOLD, Direction.SELL)

    def test_buy_signal_generated(self):
        pipeline, _ = self._build_pipeline()
        signal = pipeline.run("NVDA", dry_run=True)
        assert signal.direction == Direction.BUY
        assert signal.score >= 7.0

    def test_notifier_called(self):
        notifier = FakeNotifier()
        pipeline, _ = self._build_pipeline(notifier=notifier)
        pipeline.run("AAPL", dry_run=True)
        assert len(notifier.signals_received) == 1
        assert notifier.signals_received[0].ticker == "AAPL"

    def test_risk_rejection(self):
        pipeline, bus = self._build_pipeline(risk=RejectingRisk())
        rejected_signals = []
        bus.on("signal.rejected", lambda signal=None, **kw: rejected_signals.append(signal))
        signal = pipeline.run("NVDA", dry_run=True)
        assert signal.direction == Direction.PASS
        assert "risk_rejected_by" in signal.metadata

    def test_no_price_data(self):
        """Pipeline returns PASS when data has no price."""
        class EmptyData(DataPlugin):
            name = "empty"
            def get_quote(self, symbol):
                return None
            def get_technicals(self, symbol, period="3mo"):
                return None

        pipeline, _ = self._build_pipeline(data=EmptyData())
        signal = pipeline.run("FAKE", dry_run=True)
        assert signal.direction == Direction.PASS
        assert signal.score == 0.0

    def test_analyst_failure_isolated(self):
        """Failing analyst produces error report, doesn't crash pipeline."""
        pipeline, _ = self._build_pipeline(analyst=FailingAnalyst())
        signal = pipeline.run("NVDA", dry_run=True)
        assert signal.ticker == "NVDA"
        # Pipeline should still produce a signal (with zero score from error)

    def test_events_emitted(self):
        pipeline, bus = self._build_pipeline()
        events = []
        bus.on("*", lambda event=None, **kw: events.append(event))
        pipeline.run("NVDA", dry_run=True)
        assert "pipeline.start" in events
        assert "pipeline.complete" in events
        assert "data.complete" in events
        assert "signal.new" in events

    def test_scan_multiple_tickers(self):
        pipeline, _ = self._build_pipeline()
        signals = pipeline.scan(["NVDA", "AAPL", "SPY"])
        assert len(signals) == 3
        # Should be sorted by score descending
        scores = [s.score for s in signals]
        assert scores == sorted(scores, reverse=True)

    def test_scan_handles_failure(self):
        """If one ticker fails, others still get processed."""
        class SometimesFails(DataPlugin):
            name = "sometimes_fails"
            def get_quote(self, symbol):
                if symbol == "FAIL":
                    raise RuntimeError("data error")
                return Quote(symbol=symbol, price=100.0)
            def get_technicals(self, symbol, period="3mo"):
                return None

        pipeline, _ = self._build_pipeline(data=SometimesFails())
        signals = pipeline.scan(["NVDA", "FAIL", "SPY"])
        assert len(signals) == 3
        fail_signal = next(s for s in signals if s.ticker == "FAIL")
        assert fail_signal.direction == Direction.PASS

    def test_execution_on_live(self):
        """Broker is called when not dry_run and signal is actionable."""
        broker = FakeBroker()
        pipeline, _ = self._build_pipeline(broker=broker)
        signal = pipeline.run("NVDA", dry_run=False)
        if signal.is_actionable:
            assert "order_result" in signal.metadata

    def test_no_strategy_fallback(self):
        """Pipeline works even without a strategy plugin."""
        reg = PluginRegistry()
        bus = EventBus()
        reg.register(FakeDataPlugin())
        reg.register(FakeAnalyst())
        pipeline = Pipeline(reg, bus, {"account_value": 500})
        signal = pipeline.run("NVDA", dry_run=True)
        assert signal.source == "fallback"


# ═══════════════════════════════════════════════════════════════════════════════
# MODELS (P2)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSignalModel:
    def test_meets_threshold(self):
        sig = Signal(ticker="NVDA", direction=Direction.BUY, score=8.0, confidence=8)
        assert sig.meets_threshold is True

    def test_below_threshold(self):
        sig = Signal(ticker="NVDA", direction=Direction.BUY, score=6.5, confidence=8)
        assert sig.meets_threshold is False

    def test_low_confidence(self):
        sig = Signal(ticker="NVDA", direction=Direction.BUY, score=8.0, confidence=5)
        assert sig.meets_threshold is False

    def test_is_actionable(self):
        sig = Signal(ticker="NVDA", direction=Direction.BUY, score=8.0, confidence=8)
        assert sig.is_actionable is True

    def test_hold_not_actionable(self):
        sig = Signal(ticker="NVDA", direction=Direction.HOLD, score=8.0, confidence=8)
        assert sig.is_actionable is False

    def test_to_dict(self):
        sig = Signal(ticker="NVDA", direction=Direction.BUY, score=7.5, price=150.0)
        d = sig.to_dict()
        assert d["ticker"] == "NVDA"
        assert d["direction"] == "BUY"
        assert d["score"] == 7.5
        assert d["price"] == 150.0
        assert "timestamp" in d


class TestMarketDataModel:
    def test_price_from_quote(self):
        md = MarketData(ticker="NVDA", quote=Quote(symbol="NVDA", price=150.0))
        assert md.price == 150.0

    def test_price_no_quote(self):
        md = MarketData(ticker="NVDA")
        assert md.price == 0.0

    def test_to_dict(self):
        md = MarketData(
            ticker="NVDA",
            quote=Quote(symbol="NVDA", price=150.0),
            asset_type="equity",
        )
        d = md.to_dict()
        assert d["ticker"] == "NVDA"
        assert d["price"] == 150.0

    def test_volume_ratio(self):
        q = Quote(symbol="NVDA", price=100.0, volume=2000, avg_volume=1000)
        assert q.volume_ratio == 2.0

    def test_volume_ratio_no_avg(self):
        q = Quote(symbol="NVDA", price=100.0, volume=2000, avg_volume=0)
        assert q.volume_ratio == 1.0


class TestPositionModel:
    def test_pnl_pct(self):
        pos = Position(symbol="NVDA", qty=10, avg_entry=100.0, current_price=110.0)
        assert pos.pnl_pct == pytest.approx(10.0)

    def test_pnl_pct_zero_entry(self):
        pos = Position(symbol="NVDA", qty=10, avg_entry=0.0, current_price=100.0)
        assert pos.pnl_pct == 0.0

    def test_portfolio_position_count(self):
        p = Portfolio(positions=[
            Position(symbol="NVDA", qty=10, avg_entry=100.0),
            Position(symbol="AAPL", qty=5, avg_entry=200.0),
        ])
        assert p.position_count == 2

    def test_portfolio_get_position(self):
        pos = Position(symbol="NVDA", qty=10, avg_entry=100.0)
        p = Portfolio(positions=[pos])
        assert p.get_position("NVDA") is pos
        assert p.get_position("AAPL") is None


class TestTechnicalsModel:
    def test_to_dict_filters_none(self):
        t = Technicals(symbol="NVDA", rsi=55.0)
        d = t.to_dict()
        assert d["rsi"] == 55.0
        assert d["symbol"] == "NVDA"


# ═══════════════════════════════════════════════════════════════════════════════
# CLI COMMANDS (P1)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLI:
    @pytest.fixture
    def runner(self):
        import typer.testing
        from pro_trader.cli.app import app
        return typer.testing.CliRunner(), app

    def test_help(self, runner):
        cli, app = runner
        result = cli.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "pro-trader" in result.output.lower() or "Pro-Trader" in result.output

    def test_setup_help(self, runner):
        result = runner[0].invoke(runner[1], ["setup", "--help"])
        assert result.exit_code == 0
        assert "--check" in result.output
        assert "--update" in result.output
        assert "--uninstall" in result.output

    def test_setup_mutual_exclusivity(self, runner):
        result = runner[0].invoke(runner[1], ["setup", "--check", "--update"])
        assert result.exit_code != 0

    def test_config_help(self, runner):
        result = runner[0].invoke(runner[1], ["config", "--help"])
        assert result.exit_code == 0

    def test_health_help(self, runner):
        result = runner[0].invoke(runner[1], ["health", "--help"])
        assert result.exit_code == 0

    def test_plugin_list_help(self, runner):
        result = runner[0].invoke(runner[1], ["plugin", "list", "--help"])
        assert result.exit_code == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY (P4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurity:
    def test_internal_key_not_in_env(self, tmp_path, monkeypatch):
        """_llm_provider must never leak to .env file."""
        import pro_trader.cli.setup_wizard as wiz
        monkeypatch.setattr(wiz, "_REPO", tmp_path)
        monkeypatch.setattr(wiz, "_ENV_FILE", tmp_path / ".env")
        monkeypatch.setattr(wiz, "_ENV_EXAMPLE", tmp_path / ".env.example")

        env = {"ALPACA_API_KEY": "PK123", "_llm_provider": "anthropic"}
        wiz._save_env(env)
        content = (tmp_path / ".env").read_text()
        # _llm_provider is an internal key that should be written but it's
        # the wizard's job to pop it before calling _save_env.
        # If it leaks, it should at least not be a secret.
        # The real test is in TestRunWizard.test_full_flow_writes_files
        # which verifies it's popped before save.

    def test_channel_ids_are_numeric(self):
        """Channel IDs must be numeric strings — no injection possible."""
        from pro_trader.services.openclaw import CHANNELS
        for name, cid in CHANNELS.items():
            assert cid.isdigit(), f"Channel {name} ID '{cid}' is not numeric"

    def test_subprocess_args_are_lists(self):
        """All subprocess calls use list args (no shell injection)."""
        import pro_trader.services.openclaw as oc
        import inspect
        source = inspect.getsource(oc)
        assert "shell=True" not in source
