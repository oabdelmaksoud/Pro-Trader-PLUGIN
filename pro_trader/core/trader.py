"""
ProTrader — the main public API class.

Usage:
    from pro_trader import ProTrader

    # Quick start
    trader = ProTrader()
    signal = trader.analyze("NVDA")

    # Futures
    signal = trader.analyze("/METH26")

    # Full scan
    signals = trader.scan(["/METH26", "/M6EH26", "NVDA"])

    # Plugin management
    trader.plugins.summary()
    trader.plugins.disable("discord")

    # Custom plugin
    trader.register(MyCustomPlugin())
"""

from __future__ import annotations
import logging
from typing import Any

from pro_trader.core.config import Config
from pro_trader.core.events import EventBus
from pro_trader.core.registry import PluginRegistry
from pro_trader.core.pipeline import Pipeline
from pro_trader.core.interfaces import PluginBase
from pro_trader.models.signal import Signal

logger = logging.getLogger(__name__)


class ProTrader:
    """Main entry point for the Pro-Trader plugin framework."""

    def __init__(self, config: dict | None = None, auto_discover: bool = True,
                 plugin_categories: set[str] | None = None):
        """
        Initialize ProTrader.

        Args:
            config: Override config values (merged with defaults)
            auto_discover: If True, auto-discover and load all plugins
            plugin_categories: If provided, only load these plugin categories
                               (e.g. {"broker", "data"}). None loads all.
        """
        self.config = Config(overrides=config)
        self.bus = EventBus()
        self.plugins = PluginRegistry()
        self.plugins.set_config(self.config.data)

        if auto_discover:
            self.load_plugins(categories=plugin_categories)

        self._pipeline = Pipeline(self.plugins, self.bus, self.config.data)

    def load_plugins(self, categories: set[str] | None = None) -> int:
        """Discover and load plugins.

        Args:
            categories: If provided, only load these plugin categories.
                        None loads all.
        """
        count = self.plugins.discover(categories=categories)
        self.plugins.startup_all()
        logger.info(f"Loaded {count} plugins")
        return count

    def register(self, plugin: PluginBase) -> None:
        """Manually register a plugin."""
        self.plugins.register(plugin)

    def analyze(self, ticker: str, dry_run: bool = True) -> Signal:
        """
        Run full analysis pipeline on a single ticker.

        Args:
            ticker: Stock symbol (NVDA) or futures symbol (/METH26)
            dry_run: If True, don't execute trades
        """
        return self._pipeline.run(ticker, dry_run=dry_run)

    def scan(self, tickers: list[str] | None = None,
             dry_run: bool = True) -> list[Signal]:
        """
        Scan multiple tickers and return ranked signals.

        Args:
            tickers: List of symbols. If None, uses configured watchlist.
            dry_run: If True, don't execute trades
        """
        if tickers is None:
            tickers = self._get_watchlist()
        return self._pipeline.scan(tickers, dry_run=dry_run)

    def on(self, event: str, handler) -> None:
        """Subscribe to pipeline events."""
        self.bus.on(event, handler)

    def health(self) -> dict:
        """Get health status of all plugins."""
        return self.plugins.health()

    def _get_watchlist(self) -> list[str]:
        """Build watchlist from config."""
        wl = self.config.get("watchlist", {})
        tickers = []
        if isinstance(wl, dict):
            for key in ("futures_affordable", "futures_index", "equities"):
                tickers.extend(wl.get(key, []))
        elif isinstance(wl, list):
            tickers = wl
        return tickers or ["NVDA", "AAPL", "SPY"]

    def __repr__(self) -> str:
        plugin_count = sum(len(p) for p in self.plugins.get_all_plugins().values())
        return f"ProTrader(plugins={plugin_count}, config={self.config})"
