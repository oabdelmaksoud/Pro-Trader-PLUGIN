# Pro-Trader Plugin Architecture — Full Restructure Plan

## Current State
- Monolithic `tradingagents/` package + `scripts/` folder with 30+ loose scripts
- Single `pyproject.toml` entry point (`tradingagents = cli.main:app`)
- Hardcoded data vendor routing (yfinance/alpha_vantage only)
- Agents tightly coupled to LangGraph orchestration
- No plugin discovery, no extension points, no separation of concerns

## Target State
Three-layer architecture: **Core Library → Plugin System → Service Layer**

---

## Layer 1: Core Library (`pro_trader/core/`)
> pip-installable, zero side effects, pure logic

### Structure
```
pro_trader/
├── __init__.py              # Public API: ProTrader class
├── core/
│   ├── __init__.py
│   ├── config.py            # Unified config (merge defaults + user + env)
│   ├── registry.py          # Plugin registry (auto-discover + register)
│   ├── interfaces.py        # Abstract base classes for ALL plugin types
│   ├── events.py            # Event bus (pub/sub for plugin communication)
│   └── pipeline.py          # Pipeline orchestrator (replaces full_pipeline_scan)
├── models/
│   ├── __init__.py
│   ├── signal.py            # Signal dataclass (ticker, direction, score, etc.)
│   ├── position.py          # Position/trade models
│   ├── market_data.py       # MarketData, Quote, Technicals models
│   └── contract.py          # FuturesContract, OptionsContract models
```

### Key Interfaces (`interfaces.py`)
```python
class DataPlugin(ABC):
    """Data source plugin (yfinance, alpaca, polygon, finnhub, etc.)"""
    name: str
    provides: list[str]  # ["quotes", "technicals", "fundamentals", "news"]

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...
    @abstractmethod
    def get_technicals(self, symbol: str, period: str) -> Technicals: ...

class AnalystPlugin(ABC):
    """Analysis agent plugin (flash, macro, pulse, custom)"""
    name: str
    requires: list[str]  # ["quotes", "technicals"]

    @abstractmethod
    def analyze(self, data: MarketData) -> AnalystReport: ...

class StrategyPlugin(ABC):
    """Strategy/scoring plugin"""
    name: str

    @abstractmethod
    def score(self, data: MarketData, reports: dict) -> Signal: ...

class BrokerPlugin(ABC):
    """Execution plugin (alpaca, paper, sim)"""
    name: str

    @abstractmethod
    def submit_order(self, signal: Signal) -> OrderResult: ...

class NotifierPlugin(ABC):
    """Output plugin (discord, telegram, email, webhook)"""
    name: str

    @abstractmethod
    def notify(self, signal: Signal, context: dict) -> None: ...

class MonitorPlugin(ABC):
    """Background monitor plugin (news, dark pool, FOMC, etc.)"""
    name: str
    interval: int  # seconds

    @abstractmethod
    def check(self) -> list[Alert]: ...

class RiskPlugin(ABC):
    """Risk management plugin (circuit breaker, kelly, correlation)"""
    name: str

    @abstractmethod
    def evaluate(self, signal: Signal, portfolio: Portfolio) -> RiskVerdict: ...
```

---

## Layer 2: Plugin Packages (each independently installable)

### Built-in Plugins (ship with core)
```
pro_trader/plugins/
├── __init__.py
├── data/
│   ├── yfinance_plugin.py       # wraps tradingagents/dataflows/y_finance.py
│   ├── futures_plugin.py        # wraps tradingagents/dataflows/futures_data.py
│   └── alpaca_plugin.py         # wraps tradingagents/dataflows/alpaca_stream.py
├── analysts/
│   ├── flash_analyst.py         # Technical (Flash)
│   ├── macro_analyst.py         # Fundamentals (Macro)
│   ├── pulse_analyst.py         # Sentiment (Pulse)
│   └── langgraph_analyst.py     # Full LangGraph multi-agent (existing TradingAgentsGraph)
├── strategies/
│   ├── cooper_scorer.py         # Current scoring from get_market_data.py
│   ├── debate_strategy.py       # Bull/Bear debate → signal
│   └── futures_strategy.py      # Futures-specific scoring
├── brokers/
│   ├── alpaca_broker.py         # Alpaca paper/live
│   └── sim_broker.py            # Local simulator
├── risk/
│   ├── circuit_breaker.py       # Drawdown halt
│   ├── kelly_sizer.py           # Kelly criterion
│   ├── correlation_filter.py    # Correlation check
│   ├── earnings_filter.py       # Earnings proximity
│   └── portfolio_heat.py        # Heat map
├── monitors/
│   ├── news_monitor.py          # Breaking news (RSS + Finnhub)
│   ├── dark_pool_monitor.py     # Dark pool flows
│   ├── fomc_monitor.py          # FOMC calendar
│   ├── guru_monitor.py          # Guru tracker
│   └── futures_monitor.py       # Futures session/margin
├── notifiers/
│   ├── discord_notifier.py      # Discord webhook/bot
│   ├── console_notifier.py      # Terminal output
│   └── webhook_notifier.py      # Generic webhook
```

### Plugin Discovery (entry_points)
```toml
# pyproject.toml
[project.entry-points."pro_trader.data"]
yfinance = "pro_trader.plugins.data.yfinance_plugin:YFinancePlugin"
futures = "pro_trader.plugins.data.futures_plugin:FuturesPlugin"

[project.entry-points."pro_trader.analysts"]
flash = "pro_trader.plugins.analysts.flash_analyst:FlashAnalyst"
macro = "pro_trader.plugins.analysts.macro_analyst:MacroAnalyst"

[project.entry-points."pro_trader.brokers"]
alpaca = "pro_trader.plugins.brokers.alpaca_broker:AlpacaBroker"

# Third-party plugins would register the same way:
# [project.entry-points."pro_trader.data"]
# polygon = "pro_trader_polygon:PolygonPlugin"
```

### Plugin Config (`config/plugins.yaml` or strategy.json extension)
```yaml
plugins:
  data:
    - yfinance          # enabled by default
    - futures           # enabled
    # - polygon         # disabled (not installed)
  analysts:
    - flash
    - macro
    - pulse
  brokers:
    - alpaca
  risk:
    - circuit_breaker
    - kelly_sizer
    - portfolio_heat
  monitors:
    - news_monitor
    - fomc_monitor
    - futures_monitor
  notifiers:
    - discord
    - console

# Per-plugin config
plugin_config:
  alpaca:
    paper: true
    max_positions: 3
  discord:
    channel_ids:
      signals: "1469763123010342953"
      trades: "1234567890"
  futures:
    account_value: 500
    margin_buffer: 1.5
    max_contracts: 1
  circuit_breaker:
    max_drawdown_pct: 5.0
```

---

## Layer 3: Service Layer (deployable)

### CLI (`pro_trader/cli/`)
```
pro_trader/cli/
├── __init__.py
├── app.py               # Typer app (refactored from cli/main.py)
├── commands/
│   ├── analyze.py       # `pro-trader analyze NVDA`
│   ├── scan.py          # `pro-trader scan --watchlist`
│   ├── monitor.py       # `pro-trader monitor start/stop`
│   ├── portfolio.py     # `pro-trader portfolio status`
│   ├── plugin.py        # `pro-trader plugin list/install/enable/disable`
│   └── config.py        # `pro-trader config set/get/show`
```

### Discord Bot (`pro_trader/services/discord_bot.py`)
- Standalone bot that uses ProTrader core
- Commands: `!analyze NVDA`, `!scan`, `!portfolio`, `!quote /METH26`
- Streams signals to channels via NotifierPlugin

### Dashboard (`pro_trader/services/dashboard/`)
- FastAPI app (upgrade from raw HTTPServer)
- SSE streaming (keep existing pattern)
- REST API for portfolio, signals, plugin status
- Static frontend (keep existing HTML)

### Docker
```dockerfile
FROM python:3.12-slim
RUN pip install pro-trader[all]
CMD ["pro-trader", "monitor", "start"]
```

---

## Implementation Order (phases)

### Phase 1: Core Interfaces + Registry (foundation)
1. Create `pro_trader/core/interfaces.py` with all ABCs
2. Create `pro_trader/core/registry.py` with auto-discovery
3. Create `pro_trader/core/events.py` event bus
4. Create `pro_trader/core/config.py` unified config
5. Create `pro_trader/models/` data models

### Phase 2: Wrap Existing Code as Plugins
6. Wrap `futures_data.py` → `FuturesPlugin(DataPlugin)`
7. Wrap `y_finance.py` → `YFinancePlugin(DataPlugin)`
8. Wrap scoring logic → `CooperScorer(StrategyPlugin)`
9. Wrap `circuit_breaker.py` → `CircuitBreakerPlugin(RiskPlugin)`
10. Wrap `discord_reporter.py` → `DiscordNotifier(NotifierPlugin)`
11. Wrap existing monitors → MonitorPlugin subclasses

### Phase 3: Pipeline Orchestrator
12. Create `pro_trader/core/pipeline.py` that replaces `full_pipeline_scan.py`
    - Uses registry to find enabled plugins
    - Data plugins → Analyst plugins → Strategy plugins → Risk plugins → Broker → Notifier
13. Create `ProTrader` main class (public API)

### Phase 4: CLI Refactor
14. Refactor CLI to use `ProTrader` class
15. Add `pro-trader plugin list/enable/disable` commands
16. Add `pro-trader scan` and `pro-trader monitor` commands

### Phase 5: Service Layer
17. Discord bot service
18. Dashboard upgrade (FastAPI)
19. Docker packaging

### Phase 6: pyproject.toml + Entry Points
20. Update packaging with entry_points for plugin discovery
21. Add extras: `pip install pro-trader[discord,dashboard,alpaca]`
22. Third-party plugin template/example

---

## Migration Strategy
- **No breaking changes**: existing `scripts/` keep working during migration
- Each phase is independently deployable
- Old imports (`from tradingagents.dataflows.futures_data import ...`) stay valid via re-exports
- Plugin wrappers delegate to existing implementations (no rewrite)

## Key Design Decisions
1. **Entry points for discovery** (not file scanning) — standard Python packaging
2. **Event bus** for loose coupling — plugins don't import each other
3. **Config cascade**: defaults → plugins.yaml → env vars → CLI args
4. **Models are dataclasses** (not dicts) — type safety throughout
5. **Existing code wrapped, not rewritten** — plugins are thin adapters
