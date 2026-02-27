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
| Broker API (Alpaca) | 🔴 TODO | tradingagents/brokers/alpaca.py |
| Live data feed | 🔴 TODO | tradingagents/dataflows/alpaca_stream.py |
| OMS (real execution) | 🔴 TODO | Extends portfolio_manager.py |
| Portfolio state (Redis) | 🟡 In progress | Redis already in deps |
| OpenClaw agent wrappers | 🟡 In progress | Via CooperCorp inbox system |

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

## Team

| Agent | Role | Task |
|---|---|---|
| Sage 🔮 | Solution Architect | Broker API design |
| Forge ⚒️ | Implementation Engineer | Broker + live feed implementation |
| Pixel 🐛 | Debugger | Graph error debugging |
| Vigil 🛡️ | QA | Integration tests (paper trading) |
| Vista 🔭 | Business Analyst | Market data source research |
| Cipher 🔊 | Knowledge Curator | Docs + knowledge base |

## Upstream Sync

```bash
git fetch upstream
git merge upstream/main
```

---
*CooperCorp AGI Team | PRJ-002 | 2026-02-27*
