# Repository Guidelines — Pro-Trader

## Project Overview

Pro-Trader is a **plugin-based autonomous trading framework** built on Python 3.10+.
It uses a three-layer architecture: Core Library → Plugin System → Service Layer.

## Project Structure

```
pro_trader/              # Main package (pip-installable)
  core/                  # Framework internals
    interfaces.py        # 7 plugin ABCs (DataPlugin, AnalystPlugin, etc.)
    registry.py          # Plugin auto-discovery via entry_points + builtins
    events.py            # Pub/sub event bus (signal.*, order.*, pipeline.*)
    config.py            # Cascading config (defaults → file → env → CLI)
    pipeline.py          # Orchestrator: data → analysts → strategy → risk → broker → notify
    trader.py            # Public API entry point (ProTrader class)
  models/                # Dataclasses: Signal, MarketData, Position, FuturesContract
  plugins/               # Built-in plugins (7 categories)
    data/                # yfinance_plugin, futures_plugin
    analysts/            # flash_analyst, macro_analyst, pulse_analyst
    strategies/          # cooper_scorer
    brokers/             # alpaca_broker
    risk/                # circuit_breaker
    monitors/            # news_monitor, fomc_monitor, futures_monitor
    notifiers/           # console_notifier, discord_notifier
  services/              # External integrations
    openclaw.py          # Discord messaging bridge (openclaw v2026.3.8)
  cli/                   # Typer CLI (pro-trader command)
tradingagents/           # Legacy multi-agent system (preserved, not modified)
cli/                     # Legacy CLI (tradingagents command)
config/                  # YAML/JSON config files
scripts/                 # Operational scripts (wake_recovery, cron helpers)
```

## Build / Test / Dev Commands

```bash
# Install (core only)
pip install .

# Install (all plugins)
pip install ".[all]"

# Install (development)
pip install ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# CLI
pro-trader health
pro-trader analyze NVDA
pro-trader scan --watchlist
pro-trader plugin list
pro-trader monitor check
```

## Plugin System

All plugins implement ABCs from `pro_trader/core/interfaces.py`:

| ABC             | Key Methods                                      | Entry Point Group           |
|-----------------|--------------------------------------------------|-----------------------------|
| `DataPlugin`    | `get_quote()`, `get_technicals()`, `supports()`  | `pro_trader.data`           |
| `AnalystPlugin` | `analyze(data, context)`                         | `pro_trader.analysts`       |
| `StrategyPlugin`| `evaluate(data, reports, context)` → Signal      | `pro_trader.strategies`     |
| `BrokerPlugin`  | `submit_order()`, `get_positions()`              | `pro_trader.brokers`        |
| `RiskPlugin`    | `evaluate(signal, portfolio)`                    | `pro_trader.risk`           |
| `MonitorPlugin` | `check()` → list[dict]                          | `pro_trader.monitors`       |
| `NotifierPlugin`| `notify(signal)`, `notify_alert(alert)`          | `pro_trader.notifiers`      |

Third-party plugins register via `pyproject.toml` entry points.

## Coding Style

- Python 3.10+ (use `from __future__ import annotations`)
- Type hints on all public APIs
- Dataclasses for models (not dicts)
- Graceful degradation: all external calls must be wrapped; never crash on failure
- Plugins must not import each other — use the event bus for cross-plugin communication
- No secrets in code; use env vars (`PROTRADER_*` prefix) or config files

## Configuration

Cascading order (later wins):
1. `pro_trader/core/config.py` DEFAULT_CONFIG
2. `config/*.yaml` or `config/*.json`
3. Environment variables (`PROTRADER_LLM_PROVIDER`, `PROTRADER_SCORE_THRESHOLD`, etc.)
4. CLI flags

## OpenClaw Integration

OpenClaw is used **exclusively as a Discord messaging bridge**. All openclaw calls are
centralized in `pro_trader/services/openclaw.py`.

- Current compatible version: **v2026.3.8** (March 9, 2026)
- CLI used: `openclaw message send`, `openclaw cron list`, `openclaw cron trigger`
- The `message send` CLI is stable across all v2026.x versions
- Graceful degradation when openclaw is not installed

**Do not** add openclaw calls outside of `pro_trader/services/openclaw.py`.

## Git / Commit Guidelines

- Commit messages: `type: short description` (feat, fix, docs, refactor, test, chore)
- Keep commits focused — one logical change per commit
- Do not modify files in `tradingagents/` unless explicitly asked (legacy preserved)
- Branch naming: `claude/<description>-<session-id>`

## Key Invariants

1. `tradingagents/` is **read-only** legacy code — wrap, don't modify
2. Plugins are discovered automatically — no manual registration needed for built-in plugins
3. The pipeline never crashes — every step has fallback behavior
4. All Discord messages go through `pro_trader/services/openclaw.py`
5. Futures contracts use proxy tickers for quotes (e.g., /MESH26 → ES=F)
6. Score threshold for trades: 7.0/10 with confidence >= 7/10

## Testing

- Use `pytest` for all tests
- Plugin tests should mock external dependencies (yfinance, alpaca, openclaw)
- Test graceful degradation paths (what happens when services are unavailable)
- Futures tests should cover margin calculations and affordability filtering

## Security

- Never commit API keys, tokens, or credentials
- Use `.env` files (gitignored) for secrets
- Alpaca keys: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`
- LLM keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`
