# CooperCorp Trading — Architecture

## Overview

```
Cron Schedule (OpenClaw)
    ↓
scripts/trade_gate.py (safety gateway)
    ├── CircuitBreaker.check()      — daily loss limit
    ├── is_market_open()            — hours + holidays
    ├── EarningsFilter.check()      — earnings proximity
    ├── CorrelationFilter.check()   — sector overlap
    ├── TradeLock.acquire()         — concurrency
    ├── VIX sizing                  — volatility adjust
    └── AlpacaBroker.submit_bracket_order()
           ↓ (hard stop + target at Alpaca)
    SignalLogger.log_signal()       — all signals logged
    open_trades/{symbol}.json       — entry analysis saved

Position Monitor (every 15 min)
    ↓
TrailingStopManager.update()        — HWM-based stop
PartialExitManager.check()          — 50% at +5%
    ↓
scripts/close_position.py (on exit trigger)
    ├── AlpacaBroker.submit_order() — close
    ├── TradeLedger.record_close()  — ledger entry
    ├── TradeExecutor.on_trade_close() → PostMortem → PatternTracker
    └── TradingGraph.reflect_and_remember() — agent memory update

Signal Verifier (every 4h)
    ↓
SignalVerifier.verify_pending()     — actual vs predicted

Weekly Review (Mon 7:30 AM)
    ↓
reads: ledger, lessons, patterns, signals, equity_curve
posts: Discord #cooper-study + #paper-trades
```

## Key Files

| Layer | File | Purpose |
|---|---|---|
| Entry | `scripts/trade_gate.py` | All safety gates → Alpaca order |
| Exit | `scripts/close_position.py` | Close + learn |
| Analysis | `scripts/analyze.py` | LangGraph 7-agent pipeline |
| Config | `config/strategy.json` | All strategy parameters |
| Broker | `tradingagents/brokers/alpaca.py` | Alpaca REST + data |
| Data | `tradingagents/dataflows/` | yfinance, options flow |
| Risk | `tradingagents/risk/` | CB, lock, tags, trailing, partial |
| Filters | `tradingagents/filters/` | earnings, correlation |
| Signals | `tradingagents/signals/` | logger + verifier |
| Learning | `tradingagents/learning/` | post-mortem, patterns, adjuster |
| Ledger | `tradingagents/performance/ledger.py` | P&L tracking |
