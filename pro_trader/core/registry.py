"""
Plugin Registry — auto-discovers and manages all plugins.

Discovery methods:
  1. setuptools entry_points (for pip-installed plugins)
  2. Explicit registration via register()
  3. Built-in plugins from pro_trader/plugins/

Usage:
    registry = PluginRegistry()
    registry.discover()                          # auto-discover all
    registry.register(MyPlugin())                # manual registration
    data_plugins = registry.get_plugins("data")  # get by type
"""

from __future__ import annotations
import importlib
import logging
from typing import Type

from pro_trader.core.interfaces import (
    PluginBase, DataPlugin, AnalystPlugin, StrategyPlugin,
    BrokerPlugin, NotifierPlugin, MonitorPlugin, RiskPlugin,
)

logger = logging.getLogger(__name__)

# Map plugin base classes to their category names
PLUGIN_CATEGORIES = {
    DataPlugin: "data",
    AnalystPlugin: "analyst",
    StrategyPlugin: "strategy",
    BrokerPlugin: "broker",
    NotifierPlugin: "notifier",
    MonitorPlugin: "monitor",
    RiskPlugin: "risk",
}

# Entry point group names matching pyproject.toml
ENTRY_POINT_GROUPS = {
    "data": "pro_trader.data",
    "analyst": "pro_trader.analysts",
    "strategy": "pro_trader.strategies",
    "broker": "pro_trader.brokers",
    "notifier": "pro_trader.notifiers",
    "monitor": "pro_trader.monitors",
    "risk": "pro_trader.risk",
}


class PluginRegistry:
    """Central registry for all plugins."""

    def __init__(self):
        self._plugins: dict[str, dict[str, PluginBase]] = {
            cat: {} for cat in PLUGIN_CATEGORIES.values()
        }
        self._config: dict = {}

    def set_config(self, config: dict) -> None:
        """Set the global config (used to configure plugins on registration)."""
        self._config = config

    def register(self, plugin: PluginBase) -> None:
        """Register a plugin instance."""
        category = self._get_category(plugin)
        if category is None:
            raise TypeError(
                f"{plugin.__class__.__name__} doesn't implement any known plugin interface"
            )

        name = plugin.name
        if name in self._plugins[category]:
            logger.warning(f"Plugin '{name}' already registered in '{category}' — replacing")

        # Configure with plugin-specific config + inject trader_profile for risk plugins
        plugin_config = self._config.get("plugin_config", {}).get(name, {})
        if category == "risk" and "trader_profile" not in plugin_config:
            trader_profile = self._config.get("trader_profile", {})
            if trader_profile:
                plugin_config = {**plugin_config, "trader_profile": trader_profile}
        try:
            plugin.configure(plugin_config)
        except Exception as e:
            logger.error(f"Failed to configure plugin '{name}': {e}")

        self._plugins[category][name] = plugin
        logger.info(f"Registered {category} plugin: {plugin}")

    def unregister(self, name: str, category: str | None = None) -> bool:
        """Remove a plugin by name. If category is None, search all categories."""
        if category:
            if name in self._plugins.get(category, {}):
                del self._plugins[category][name]
                return True
            return False

        for cat in self._plugins:
            if name in self._plugins[cat]:
                del self._plugins[cat][name]
                return True
        return False

    def get_plugin(self, name: str, category: str | None = None) -> PluginBase | None:
        """Get a single plugin by name."""
        if category:
            return self._plugins.get(category, {}).get(name)

        for cat in self._plugins.values():
            if name in cat:
                return cat[name]
        return None

    def get_plugins(self, category: str) -> list[PluginBase]:
        """Get all enabled plugins in a category."""
        return [p for p in self._plugins.get(category, {}).values() if p.enabled]

    def get_all_plugins(self) -> dict[str, list[PluginBase]]:
        """Get all plugins grouped by category."""
        return {cat: list(plugins.values()) for cat, plugins in self._plugins.items()}

    def discover(self) -> int:
        """
        Auto-discover plugins from:
          1. setuptools entry_points
          2. Built-in plugins

        Returns number of plugins discovered.
        """
        count = 0
        count += self._discover_entry_points()
        count += self._discover_builtins()
        return count

    def _discover_entry_points(self) -> int:
        """Discover plugins registered via setuptools entry_points."""
        count = 0
        try:
            from importlib.metadata import entry_points
        except ImportError:
            return 0

        for category, group in ENTRY_POINT_GROUPS.items():
            try:
                eps = entry_points(group=group)
            except TypeError:
                # Python 3.9 compatibility
                all_eps = entry_points()
                eps = all_eps.get(group, [])

            for ep in eps:
                try:
                    plugin_cls = ep.load()
                    if isinstance(plugin_cls, type) and issubclass(plugin_cls, PluginBase):
                        plugin = plugin_cls()
                        self.register(plugin)
                        count += 1
                    elif isinstance(plugin_cls, PluginBase):
                        self.register(plugin_cls)
                        count += 1
                except Exception as e:
                    logger.warning(f"Failed to load entry_point '{ep.name}': {e}")

        return count

    def _discover_builtins(self) -> int:
        """Discover built-in plugins from pro_trader.plugins package."""
        count = 0
        builtin_modules = [
            "pro_trader.plugins.data.realtime_plugin",
            "pro_trader.plugins.data.yfinance_plugin",
            "pro_trader.plugins.data.futures_plugin",
            "pro_trader.plugins.analysts.flash_analyst",
            "pro_trader.plugins.analysts.macro_analyst",
            "pro_trader.plugins.analysts.pulse_analyst",
            "pro_trader.plugins.strategies.cooper_scorer",
            "pro_trader.plugins.risk.circuit_breaker_plugin",
            "pro_trader.plugins.notifiers.discord_notifier",
            "pro_trader.plugins.notifiers.console_notifier",
            "pro_trader.plugins.monitors.news_monitor_plugin",
            "pro_trader.plugins.monitors.fomc_monitor_plugin",
            "pro_trader.plugins.monitors.futures_monitor_plugin",
        ]

        for module_path in builtin_modules:
            try:
                module = importlib.import_module(module_path)
                # Look for a Plugin class or plugin instance
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type)
                            and issubclass(attr, PluginBase)
                            and attr is not PluginBase
                            and not any(attr is base for base in PLUGIN_CATEGORIES)):
                        # Check if already registered
                        instance = attr()
                        if not self.get_plugin(instance.name):
                            self.register(instance)
                            count += 1
            except ImportError:
                pass  # Plugin not yet implemented — that's fine during dev
            except Exception as e:
                logger.debug(f"Error loading builtin {module_path}: {e}")

        return count

    def enable(self, name: str) -> bool:
        """Enable a plugin by name."""
        plugin = self.get_plugin(name)
        if plugin:
            plugin.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a plugin by name."""
        plugin = self.get_plugin(name)
        if plugin:
            plugin.enabled = False
            return True
        return False

    def startup_all(self) -> None:
        """Call startup() on all enabled plugins."""
        for cat in self._plugins.values():
            for plugin in cat.values():
                if plugin.enabled:
                    try:
                        plugin.startup()
                    except Exception as e:
                        logger.error(f"Plugin '{plugin.name}' startup failed: {e}")

    def shutdown_all(self) -> None:
        """Call shutdown() on all plugins."""
        for cat in self._plugins.values():
            for plugin in cat.values():
                try:
                    plugin.shutdown()
                except Exception as e:
                    logger.error(f"Plugin '{plugin.name}' shutdown failed: {e}")

    def health(self) -> dict:
        """Get health status of all plugins."""
        status = {}
        for cat, plugins in self._plugins.items():
            status[cat] = {}
            for name, plugin in plugins.items():
                try:
                    status[cat][name] = plugin.health_check()
                except Exception as e:
                    status[cat][name] = {"name": name, "status": "error", "error": str(e)}
        return status

    def summary(self) -> str:
        """Human-readable summary of registered plugins."""
        lines = ["Plugin Registry:"]
        for cat, plugins in self._plugins.items():
            if plugins:
                lines.append(f"  {cat}:")
                for plugin in plugins.values():
                    lines.append(f"    {plugin}")
        return "\n".join(lines)

    @staticmethod
    def _get_category(plugin: PluginBase) -> str | None:
        """Determine which category a plugin belongs to."""
        for base_cls, category in PLUGIN_CATEGORIES.items():
            if isinstance(plugin, base_cls):
                return category
        return None
