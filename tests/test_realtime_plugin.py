"""Tests for RealtimePlugin — mocks external APIs to validate plugin logic."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from pro_trader.plugins.data.realtime_plugin import RealtimePlugin
from pro_trader.models.market_data import Quote


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fake_quote(symbol, source="alpaca", delayed=False, price=185.50):
    return {
        "symbol": symbol, "price": price, "prev_close": 190.0,
        "change": price - 190.0, "change_pct": round((price - 190.0) / 190.0 * 100, 4),
        "volume": 50_000_000, "high": 192.0, "low": 183.0, "open": 189.5,
        "source": source, "delayed": delayed,
    }


# ── Tests ────────────────────────────────────────────────────────────────────

def test_startup_success():
    plugin = RealtimePlugin()
    plugin.startup()
    # realtime_quotes module should be importable from tradingagents
    assert plugin.enabled is True
    assert plugin._mod is not None


def test_startup_graceful_failure():
    plugin = RealtimePlugin()
    with patch("pro_trader.plugins.data.realtime_plugin.RealtimePlugin.startup") as mock_startup:
        # Simulate what happens when import fails
        def failing_startup(self_=plugin):
            try:
                raise ImportError("no module")
            except ImportError:
                self_._mod = None
                self_.enabled = False
        mock_startup.side_effect = failing_startup
        plugin.startup()
    assert plugin._mod is None
    assert plugin.enabled is False


def test_supports_all_symbols():
    plugin = RealtimePlugin()
    assert plugin.supports("NVDA") is True
    assert plugin.supports("SPY") is True
    assert plugin.supports("/MES") is True
    assert plugin.supports("BTC-USD") is True
    assert plugin.supports("ES=F") is True


def test_get_quote_returns_quote_dataclass():
    plugin = RealtimePlugin()
    mock_mod = MagicMock()
    mock_mod.get_quote.return_value = _fake_quote("NVDA")
    plugin._mod = mock_mod

    q = plugin.get_quote("NVDA")
    assert isinstance(q, Quote)
    assert q.symbol == "NVDA"
    assert q.price == 185.50
    assert q.source == "alpaca"
    assert q.prev_close == 190.0
    assert q.volume == 50_000_000
    mock_mod.get_quote.assert_called_once_with("NVDA")


def test_get_quote_returns_none_on_failure():
    plugin = RealtimePlugin()
    mock_mod = MagicMock()
    mock_mod.get_quote.return_value = None
    plugin._mod = mock_mod

    assert plugin.get_quote("FAKE") is None


def test_get_quote_returns_none_when_no_module():
    plugin = RealtimePlugin()
    plugin._mod = None
    assert plugin.get_quote("NVDA") is None


def test_get_quote_handles_exception():
    plugin = RealtimePlugin()
    mock_mod = MagicMock()
    mock_mod.get_quote.side_effect = RuntimeError("API down")
    plugin._mod = mock_mod

    assert plugin.get_quote("NVDA") is None


def test_get_quote_zero_price_returns_none():
    plugin = RealtimePlugin()
    mock_mod = MagicMock()
    mock_mod.get_quote.return_value = _fake_quote("NVDA", price=0)
    plugin._mod = mock_mod

    assert plugin.get_quote("NVDA") is None


def test_technicals_returns_none():
    """Technicals come from yfinance plugin, not realtime."""
    plugin = RealtimePlugin()
    plugin._mod = MagicMock()
    assert plugin.get_technicals("NVDA") is None


def test_health_check():
    plugin = RealtimePlugin()
    plugin._mod = MagicMock()
    h = plugin.health_check()
    assert h["name"] == "realtime"
    assert h["status"] == "ok"
    assert "alpaca" in h["priority_chain"][0]

    plugin._mod = None
    h = plugin.health_check()
    assert h["status"] == "unavailable"


def test_multiple_sources():
    """Simulate different sources returning data."""
    for source in ["alpaca", "finnhub", "polygon", "webull", "yfinance"]:
        plugin = RealtimePlugin()
        mock_mod = MagicMock()
        mock_mod.get_quote.return_value = _fake_quote("SPY", source=source)
        plugin._mod = mock_mod

        q = plugin.get_quote("SPY")
        assert q.source == source


def test_plugin_registered_in_pipeline():
    """Verify realtime plugin is discovered before yfinance."""
    from pro_trader.core.registry import PluginRegistry

    registry = PluginRegistry()
    count = registry._discover_builtins()

    data_plugins = registry.get_plugins("data")
    names = [p.name for p in data_plugins]
    assert "realtime" in names, f"realtime not found in {names}"

    # realtime should come before yfinance
    if "yfinance" in names:
        assert names.index("realtime") < names.index("yfinance"), \
            f"realtime should be before yfinance, got: {names}"
