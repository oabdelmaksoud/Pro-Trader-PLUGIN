# Pro-Trader

A plugin-based trading framework for Python. Analyze stocks and futures, score trade signals, and execute through your broker — all from a simple API or CLI.

```python
from pro_trader import ProTrader

trader = ProTrader()
signal = trader.analyze("NVDA")
signals = trader.scan(["NVDA", "SPY", "AAPL"])
```

---

## Install

```bash
# Core (data + scoring)
pip install pro-trader

# With AI analysts
pip install "pro-trader[agents]"

# Everything
pip install "pro-trader[all]"

# From source
git clone https://github.com/oabdelmaksoud/Pro-Trader-SKILL.git
cd Pro-Trader-SKILL
pip install -e ".[all]"
```

---

## CLI

```bash
pro-trader analyze NVDA          # Analyze a stock
pro-trader analyze /METH26       # Analyze a futures contract
pro-trader scan --watchlist       # Scan your watchlist
pro-trader plugin list            # Show loaded plugins
pro-trader health                 # Check system health
pro-trader setup                  # Interactive setup wizard
```

---

## How It Works

Pro-Trader runs a 6-step pipeline for every ticker:

```
1. Data        →  Fetch quotes, technicals, news
2. Analysts    →  AI agents analyze in parallel (Flash, Macro, Pulse)
3. Strategy    →  Score the signal (0-10)
4. Risk        →  Check risk gates (drawdown, sizing, correlation)
5. Broker      →  Execute trade if approved
6. Notify      →  Send alerts (Discord, console)
```

Each step is handled by **plugins**. You can swap, disable, or add your own at any point.

---

## Plugins

Everything is a plugin. Pro-Trader ships with 12 built-in:

| Category | Plugins | What they do |
|----------|---------|--------------|
| **Data** | `yfinance`, `futures` | Fetch quotes, technicals, fundamentals |
| **Analysts** | `flash`, `macro`, `pulse` | AI-powered technical, fundamental, and sentiment analysis |
| **Strategy** | `cooper_scorer` | Composite scoring with configurable thresholds |
| **Risk** | `circuit_breaker` | Drawdown halt, daily loss limits |
| **Monitors** | `news`, `fomc`, `futures_monitor` | Background alerts for news, FOMC dates, sessions |
| **Notifiers** | `discord`, `console` | Send signal cards to Discord or terminal |
| **Broker** | `alpaca` | Paper and live trading via Alpaca |

### Writing Your Own Plugin

```python
from pro_trader.core.interfaces import DataPlugin
from pro_trader.models.market_data import Quote

class MyDataPlugin(DataPlugin):
    name = "my_source"
    version = "1.0.0"

    def get_quote(self, symbol):
        return Quote(symbol=symbol, price=100.0, source="my_source")

    def get_technicals(self, symbol, period="3mo"):
        return None

# Register it
trader = ProTrader()
trader.register(MyDataPlugin())
```

Or register via `pyproject.toml` for automatic discovery:

```toml
[project.entry-points."pro_trader.data"]
my_source = "my_package:MyDataPlugin"
```

### Plugin Types

| Interface | Methods | Entry Point |
|-----------|---------|-------------|
| `DataPlugin` | `get_quote()`, `get_technicals()` | `pro_trader.data` |
| `AnalystPlugin` | `analyze(data) -> report` | `pro_trader.analysts` |
| `StrategyPlugin` | `evaluate(data, reports) -> Signal` | `pro_trader.strategies` |
| `BrokerPlugin` | `submit_order()`, `get_positions()` | `pro_trader.brokers` |
| `RiskPlugin` | `evaluate(signal, portfolio)` | `pro_trader.risk` |
| `MonitorPlugin` | `check() -> alerts` | `pro_trader.monitors` |
| `NotifierPlugin` | `notify(signal)` | `pro_trader.notifiers` |

---

## Python API

```python
from pro_trader import ProTrader

trader = ProTrader(config={
    "llm_provider": "anthropic",
    "score_threshold": 7.0,
})

# Analyze
signal = trader.analyze("NVDA", dry_run=True)
print(f"{signal.ticker}: {signal.direction.value} score={signal.score}")

# Scan multiple
signals = trader.scan(["NVDA", "SPY", "/METH26"])
for s in signals:
    print(f"  {s.ticker}: {s.score:.1f}")

# Plugin control
trader.plugins.disable("discord")
trader.plugins.enable("discord")

# Event hooks
trader.on("signal.new", lambda s: print(f"New: {s.ticker}"))
trader.on("order.filled", lambda o, r: print(f"Filled: {r.order_id}"))
```

### Events

Plugins communicate through events, not imports:

| Event | When |
|-------|------|
| `signal.new` | New signal scored |
| `signal.approved` | Passed risk gates |
| `signal.rejected` | Blocked by risk |
| `order.filled` | Trade executed |
| `monitor.alert` | Background alert fired |
| `risk.halt` | Circuit breaker tripped |

---

## Configuration

Settings cascade (last wins):

1. Built-in defaults
2. Config files (`config/*.json`)
3. Environment variables (`PROTRADER_*`)
4. CLI flags / `ProTrader(config={...})`

### Environment Variables

```env
# Broker
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# AI Analysts
ANTHROPIC_API_KEY=your_key

# Overrides
PROTRADER_LLM_PROVIDER=anthropic
PROTRADER_SCORE_THRESHOLD=7.0
```

### Config File (`config/strategy.json`)

```json
{
  "watchlist": {
    "equities": ["NVDA", "AAPL", "SPY"],
    "futures": ["/MET", "/MCD", "/M6A"]
  },
  "score_threshold": 7.0,
  "futures_position": {
    "max_contracts": 1,
    "max_margin_pct": 0.60
  }
}
```

---

## Futures Support

Pro-Trader supports 13 micro futures contracts with automatic margin calculation and affordability filtering based on your account size.

| Contract | Asset Class |
|----------|-------------|
| `/MET` Micro Ether | Crypto |
| `/MCD` Micro CAD | FX |
| `/M6A` Micro AUD | FX |
| `/M6B` Micro GBP | FX |
| `/M6E` Micro EUR | FX |
| `/BFF` Bitcoin Friday | Crypto |
| `/1OZ` 1oz Gold | Commodity |
| `/MSF` Micro CHF | FX |
| `/MNG` Micro NatGas | Commodity |
| `/MES` Micro S&P 500 | Index |
| `/MNQ` Micro Nasdaq | Index |
| `/MYM` Micro Dow | Index |
| `/MCL` Micro Crude | Commodity |

---

## Risk Management

| Rule | Default |
|------|---------|
| Score threshold | 7.0/10 with confidence >= 7/10 |
| Stop loss | -3% trailing |
| Take profit | +8% |
| Partial exit | 50% at +5% |
| Drawdown halt | Portfolio down 5% |
| Kelly sizing | Half-Kelly from rolling win rate |
| Futures margin cap | 60% of account |

---

## OpenClaw Integration

Pro-Trader can use [OpenClaw](https://github.com/openclaw/openclaw) as a Discord messaging bridge. If OpenClaw isn't installed, notifications silently skip (graceful degradation).

```python
from pro_trader.services.openclaw import send_discord

send_discord("your_channel_id", "Signal: BUY NVDA score 8.5")
```

All OpenClaw calls are centralized in `pro_trader/services/openclaw.py`. Compatible with OpenClaw v2026.3.x.

---

## Project Structure

```
pro_trader/
├── core/               # Framework: interfaces, registry, pipeline, config, events
├── models/             # Dataclasses: Signal, MarketData, Position, Order
├── plugins/            # 12 built-in plugins (7 categories)
├── services/           # External integrations (OpenClaw)
└── cli/                # CLI app + setup wizard

tradingagents/          # Legacy multi-agent system (preserved)
config/                 # Config files
scripts/                # Operational scripts
tests/                  # Test suite (160+ tests)
```

---

## Development

```bash
pip install -e ".[dev]"
pytest                   # Run tests
ruff check .             # Lint
```

---

## Built On

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — base multi-agent framework
- [OpenClaw](https://github.com/openclaw/openclaw) — Discord messaging bridge
- [Alpaca Markets](https://alpaca.markets) — trade execution
- [yfinance](https://github.com/ranaroussi/yfinance) — market data

---

*Pro-Trader v1.1.0*
