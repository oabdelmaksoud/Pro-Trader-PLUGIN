# CooperCorp Trading System — PRJ-002

Forked from [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).

## What This Is

A multi-agent LLM trading framework extended for **live broker execution** (Alpaca),
real-time market data feeds, and full CooperCorp AGI team integration.

## Architecture

```
Analyst Team → Researcher Debate → Trader → Risk Team → Portfolio Manager → [BROKER API]
```

## CooperCorp Extensions (PRJ-002)

| Layer | Status | Notes |
|---|---|---|
| Broker API (Alpaca) | ✅ Built | `tradingagents/brokers/alpaca.py` — Full Alpaca integration |
| Live data feed | ✅ Built | `tradingagents/dataflows/alpaca_stream.py` — Real-time streaming |
| OMS (real execution) | ✅ Built | `tradingagents/execution/executor.py` — Order management |
| Risk controls | ✅ Built | Circuit breaker, portfolio heat monitoring |
| News & sentiment | ✅ Built | News aggregator, Google News, Reddit, Stocktwits |
| Options data | ✅ Built | CBOE options chain, IV percentile, options flow |
| Real-time quotes | ✅ Built | `realtime_quotes.py`, Polygon, Finnhub integration |
| Discord reporter | ✅ Built | OpenClaw-integrated alerts via Discord |
| Portfolio state | 🟡 Config | Strategy config in `config/strategy.json` |

## LLM Configuration (CooperCorp)

```python
config = {
    "llm_provider": "anthropic",
    "deep_think_llm": "claude-opus-4-6",
    "quick_think_llm": "claude-sonnet-4-6",
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,
}
```

## Trading Scripts

| Script | Purpose |
|---|---|
| `run_live.py` | Main live trading entry point |
| `trade_gate.py` | Trade execution with risk checks |
| `stream_manager.py` | Market data stream management |
| `get_market_data.py` | Multi-source market data fetching |
| `account_status.py` | Alpaca account status |
| `close_position.py` | Position closure with Discord alerts |
| `reconcile_positions.py` | Position reconciliation |
| `futures_monitor.py` | Futures market monitoring |
| `gold_monitor.py` | Gold/commodities monitoring |
| `weekly_review.py` | Weekly performance review |
| `backtest.py` | Strategy backtesting |

## Team

| Agent | Role | Task |
|---|---|---|
| Sage 🔮 | Solution Architect | Broker API design |
| Forge ⚒️ | Implementation Engineer | Broker + live feed implementation |
| Pixel 🐛 | Debugger | Graph error debugging |
| Vigil 🛡️ | QA | Integration tests (paper trading) |
| Vista 🔭 | Business Analyst | Market data source research |
| Cipher 🔊 | Knowledge Curator | Docs + knowledge base |

## Strategy Configuration

See `config/strategy.json` for:
- **Scoring weights**: catalyst (0.3), technical (0.25), sentiment (0.2), fundamental (0.15), risk_reward (0.1)
- **Position sizing**: Max 2 positions, 5% default, stop at 3%, target 8%
- **Risk management**: VIX-based sizing, correlation sector limits, daily loss cap
- **Watchlist**: Tier 1 (13 tickers), Tier 2 (6 sectors), ETFs, focus list

## Upstream Sync

```bash
git fetch upstream
git merge upstream/main
```

---
*CooperCorp AGI Team | PRJ-002 | 2026-02-28*
