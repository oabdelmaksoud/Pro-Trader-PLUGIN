# CooperCorp Trading — Changelog

## [Unreleased]

## [0.3.0] — 2026-02-27
### Added (CooperCorp layer — all new on top of upstream)
- `tradingagents/brokers/alpaca.py` — AlpacaBroker with bracket orders, intraday bars, retry logic
- `tradingagents/execution/executor.py` — TradeExecutor with all safety gates
- `tradingagents/risk/` — circuit_breaker, trade_lock, trade_tags, trailing_stop, partial_exit
- `tradingagents/filters/` — earnings_filter, correlation_filter
- `tradingagents/signals/` — signal_logger, signal_verifier
- `tradingagents/learning/` — post_mortem, pattern_tracker, score_adjuster
- `tradingagents/performance/ledger.py` — TradeLedger
- `tradingagents/utils/` — market_hours, strategy_config
- `tradingagents/dataflows/options_flow.py` — real options chain screening
- `config/strategy.json` — centralized strategy parameters
- `scripts/` — trade_gate, close_position, analyze, reconcile_positions, backtest, performance, signal_accuracy, weekly_review, equity_snapshot, rotate_logs
- `tests/test_broker.py` — pytest suite
- `WATCHLIST.md` — 3-tier ticker universe
- `COOPERCORP.md` — project overview

### OpenClaw Integration
- 20 cron jobs for fully autonomous paper trading
- 7 trading agents registered (flash, macro, pulse, bull, bear, risk-mgr, executor)
- Discord posting via OpenClaw message tool
- Signal tracking → post-mortem → pattern learning → score adjustment loop

## [0.2.0] — 2026-02 (Upstream: TauricResearch)
- Multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x)

## [0.1.0] — 2025-12 (Upstream: TauricResearch)
- Initial TradingAgents framework release
