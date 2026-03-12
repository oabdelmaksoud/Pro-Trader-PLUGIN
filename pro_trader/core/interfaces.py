"""
Plugin interfaces — Abstract Base Classes for ALL plugin types.

Every plugin implements one of these ABCs. The registry discovers and
loads them via setuptools entry_points or explicit registration.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional

from pro_trader.models.signal import Signal
from pro_trader.models.market_data import MarketData, Quote, Technicals
from pro_trader.models.position import Order, OrderResult, Portfolio, AccountSummary


# ─── Base ────────────────────────────────────────────────────────────────────

class PluginBase(ABC):
    """Base class for all plugins."""

    name: str = "unnamed"
    version: str = "0.1.0"
    description: str = ""
    enabled: bool = True

    def configure(self, config: dict) -> None:
        """Called once after registration with plugin-specific config."""
        pass

    def startup(self) -> None:
        """Called when the plugin system starts (after all plugins loaded)."""
        pass

    def shutdown(self) -> None:
        """Called on clean shutdown."""
        pass

    def health_check(self) -> dict:
        """Return plugin health status."""
        return {"name": self.name, "version": self.version, "status": "ok"}

    def __repr__(self) -> str:
        state = "enabled" if self.enabled else "disabled"
        return f"<{self.__class__.__name__} '{self.name}' v{self.version} [{state}]>"


# ─── Data Plugins ────────────────────────────────────────────────────────────

class DataPlugin(PluginBase):
    """
    Data source plugin — provides market quotes, technicals, fundamentals, news.

    Examples: YFinancePlugin, AlpacaPlugin, PolygonPlugin, FuturesPlugin
    """

    provides: list[str] = []  # ["quotes", "technicals", "fundamentals", "news"]

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch current price quote for a symbol."""
        ...

    @abstractmethod
    def get_technicals(self, symbol: str, period: str = "3mo") -> Optional[Technicals]:
        """Calculate technical indicators for a symbol."""
        ...

    def get_fundamentals(self, symbol: str) -> dict:
        """Fetch fundamental data (P/E, revenue, etc.). Override if supported."""
        return {}

    def get_news(self, symbol: str, limit: int = 10) -> list[dict]:
        """Fetch recent news for a symbol. Override if supported."""
        return []

    def get_market_data(self, symbol: str, full: bool = False) -> MarketData:
        """Convenience: aggregate all data into a MarketData object."""
        quote = self.get_quote(symbol)
        technicals = self.get_technicals(symbol) if full else None
        fundamentals = self.get_fundamentals(symbol) if full else {}
        news = self.get_news(symbol) if full else []
        return MarketData(
            ticker=symbol,
            quote=quote,
            technicals=technicals,
            fundamentals=fundamentals,
            news=news,
        )

    def supports(self, symbol: str) -> bool:
        """Check if this plugin can handle the given symbol."""
        return True


# ─── Analyst Plugins ─────────────────────────────────────────────────────────

class AnalystPlugin(PluginBase):
    """
    Analysis agent plugin — takes MarketData, produces a report.

    Examples: FlashAnalyst (technical), MacroAnalyst (fundamental),
              PulseAnalyst (sentiment), LangGraphAnalyst (full multi-agent)
    """

    requires: list[str] = []  # ["quotes", "technicals"] — what data it needs

    @abstractmethod
    def analyze(self, data: MarketData, context: dict | None = None) -> dict:
        """
        Run analysis and return a report dict.

        Returns:
            {
                "report": str,          # Full text report
                "score": float,         # 0-10
                "direction": str,       # BUY/SELL/HOLD
                "key_points": list,     # Summary bullets
                "metadata": dict,       # Extra data
            }
        """
        ...


# ─── Strategy Plugins ────────────────────────────────────────────────────────

class StrategyPlugin(PluginBase):
    """
    Scoring/strategy plugin — combines data + reports into a Signal.

    Examples: CooperScorer, DebateStrategy, FuturesStrategy
    """

    @abstractmethod
    def evaluate(self, data: MarketData, reports: dict[str, dict],
                 context: dict | None = None) -> Signal:
        """
        Produce a trade signal from aggregated data and analyst reports.

        Args:
            data: Market data
            reports: {"flash": {...}, "macro": {...}, "pulse": {...}}
            context: Intel bonuses, portfolio state, etc.
        """
        ...


# ─── Broker Plugins ──────────────────────────────────────────────────────────

class BrokerPlugin(PluginBase):
    """
    Execution plugin — submits orders and tracks positions.

    Examples: AlpacaBroker, SimBroker, IBKRBroker
    """

    supported_assets: list[str] = ["equity"]

    @abstractmethod
    def submit_order(self, order: Order) -> OrderResult:
        """Submit a trade order."""
        ...

    @abstractmethod
    def get_positions(self) -> list:
        """Get current open positions."""
        ...

    @abstractmethod
    def get_portfolio(self) -> Portfolio:
        """Get portfolio snapshot (cash, equity, positions)."""
        ...

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Override if supported."""
        return False

    def get_account_summary(self) -> AccountSummary:
        """Return account summary for profile sync. Override to provide real data."""
        return AccountSummary(broker_name=self.name)

    def supports_asset(self, asset_type: str) -> bool:
        """Check if this broker supports a given asset type."""
        return asset_type in self.supported_assets


# ─── Notifier Plugins ────────────────────────────────────────────────────────

class NotifierPlugin(PluginBase):
    """
    Output plugin — sends signals/alerts to external channels.

    Examples: DiscordNotifier, TelegramNotifier, WebhookNotifier, ConsoleNotifier
    """

    @abstractmethod
    def notify(self, signal: Signal, context: dict | None = None) -> bool:
        """
        Send a notification. Returns True if successful.

        Args:
            signal: The trade signal to communicate
            context: Extra context (channel, format, urgency, etc.)
        """
        ...

    def notify_alert(self, alert: dict) -> bool:
        """Send a generic alert (news, risk warning, etc.). Override if needed."""
        return False


# ─── Monitor Plugins ─────────────────────────────────────────────────────────

class MonitorPlugin(PluginBase):
    """
    Background monitor plugin — runs periodically, emits alerts/data.

    Examples: NewsMonitor, DarkPoolMonitor, FOMCMonitor, FuturesMonitor
    """

    interval: int = 300  # check interval in seconds

    @abstractmethod
    def check(self) -> list[dict]:
        """
        Run a monitoring check. Returns list of alerts/signals.

        Each alert: {"type": str, "severity": str, "message": str, "data": dict}
        """
        ...

    def get_state(self) -> dict:
        """Return current monitor state for dashboard/API. Override if needed."""
        return {}


# ─── Risk Plugins ────────────────────────────────────────────────────────────

class RiskPlugin(PluginBase):
    """
    Risk management plugin — evaluates signals against risk rules.

    Examples: CircuitBreaker, KellySizer, CorrelationFilter, EarningsFilter
    """

    @abstractmethod
    def evaluate(self, signal: Signal, portfolio: Portfolio) -> dict:
        """
        Evaluate a signal against risk rules.

        Returns:
            {
                "approved": bool,
                "reason": str,
                "adjustments": dict,   # e.g. {"position_size": 0.5}
                "warnings": list[str],
            }
        """
        ...
