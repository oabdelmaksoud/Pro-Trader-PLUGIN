# 🦅 ProTrader — Autonomous Multi-Agent Trading System

> **Target:** $1,000,000 from $100,499 | Paper trading via Alpaca | Zero manual steps

[![CI](https://img.shields.io/badge/CI-8%2F8%20passing-brightgreen)](https://github.com/oabdelmaksoud/protrader)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Overview

ProTrader is a fully autonomous 7-agent trading pipeline built on [OpenClaw](https://openclaw.ai). It runs 24/7, scans markets 5× per day, manages risk automatically, and posts real-time signals to Discord. No API keys for LLMs — all inference runs natively through OpenClaw.

**Current portfolio:** ~$100,394 | **Status:** Active, paper trading | **Week:** 2

---

## Architecture

```
Cron (5× daily) → Cooper 🦅
  │
  ├── get_market_data.py        # 15+ sources, no LLM, pure data
  ├── guru_tracker.py           # 13F + STOCK Act → score bonuses
  │
  └── full_pipeline_scan.py
        ├── Flash 📈            # Technical analysis (parallel)
        ├── Macro 🌍            # Fundamentals + news (parallel)
        ├── Pulse 💬            # Sentiment + options flow (parallel)
        ├── situation_memory    # BM25 memory lookup (Gap 1)
        ├── research_synthesizer # Synthesis (Gap 3)
        ├── Bull 🐂 ↔ Bear 🐻  # Multi-round debate (Gap 4)
        ├── signal_processor    # Signal extraction (Gap 5)
        └── load_intelligence_context()
              ├── guru_signals.json
              ├── sentiment_scores.json
              └── short_interest.json
                    │
                    └── trade_gate.py  # Gates 1-5 + Kelly + drawdown
                          │
                          └── Alpaca Bracket Order
                                │
                                └── close_position.py
                                      ├── reflect_on_trade.py  (async, Gap 2)
                                      └── position_calibrator.py (async)
```

---

## Agent Roster

| Agent | Emoji | Model | Role |
|-------|-------|-------|------|
| Flash | 📈 | claude-sonnet-4-6 | Technical analysis — price action, MACD, BB, VWAP |
| Macro | 🌍 | claude-sonnet-4-6 | Fundamentals, news, economic calendar |
| Pulse | 💬 | claude-sonnet-4-6 | Sentiment, options flow, dark pool |
| Bull | 🐂 | claude-opus-4-6 | Bullish researcher — debate round 1 |
| Bear | 🐻 | claude-opus-4-6 | Bearish researcher — debate round 1 |
| Risk | 🛡️ | claude-sonnet-4-6 | Risk Manager — position sizing, correlation |
| Executor | ⚡ | claude-sonnet-4-6 | Trade execution, bracket orders, P&L |

---

## Data Sources (15+)

| Source | Data |
|--------|------|
| Alpaca IEX WebSocket | Real-time quotes (primary) |
| Finnhub API | News, earnings, options chain |
| Alpha Vantage | MACD, Bollinger Bands |
| Polygon.io | Options flow, tick data |
| yfinance | Sector ETFs, futures, pre-market gaps |
| SEC EDGAR | 13F filings, Form 4 insider trades |
| OpenInsider RSS | Insider cluster buys |
| House/Senate Stock Watcher | STOCK Act political disclosures |
| Finviz | Short interest (FINRA bi-weekly) |
| GuruFocus RSS | Guru news signals |
| NY Fed | SOFR/EFFR liquidity stress |
| Earnings Whisper | EPS whisper vs. consensus |
| SpotGamma | GEX (gamma exposure) levels |
| 20 RSS feeds | Breaking news: Reuters, Al Jazeera, SEC, FDA, Fed, DOJ, etc. |
| yfinance / Alpaca | Pre-market gap analysis |

---

## Key Scripts

### Core Pipeline
```
scripts/
├── get_market_data.py          # Data gatherer — 15+ sources, no LLM
├── full_pipeline_scan.py       # Full 5-gap pipeline: data → agents → debate → signal → gate
├── trade_gate.py               # Execution gateway: Gates 1-5 + Kelly + guru bonus + drawdown
├── close_position.py           # Close gateway + outcome logging + async reflection
└── quick_quote.py              # Fast live quote (1-5 tickers, ~3s)
```

### Intelligence / Alpha Generation
```
scripts/
├── guru_tracker.py             # 13F + political trades + GuruFocus → score bonuses (6 AM daily)
├── whale_tracker.py            # Congressional/insider/dark pool → #war-room (every 4h)
├── news_trade_trigger.py       # News-to-trade bridge: TIER 1/2 → trade_gate
├── futures_monitor.py          # Sunday pre-week futures bias card
├── earnings_calendar.py        # Earnings pre-position + beat/miss (4 PM daily)
├── economic_calendar.py        # CPI/FOMC/NFP 60-min warnings (hourly 9-4 PM)
├── fomc_monitor.py             # FOMC 3-day pre-position window (8 AM daily)
├── short_interest.py           # Short float >20% squeeze setups (Mon 8 AM)
├── etf_flow_tracker.py         # Sector rotation via ETF volume (Mon 8 AM)
├── dark_pool_monitor.py        # $1M+ block trades on watchlist (every 30 min)
├── sentiment_aggregator.py     # Finnhub + news sentiment scores (8 AM daily)
├── repo_rate_monitor.py        # SOFR/EFFR liquidity stress (9 AM daily)
├── drawdown_monitor.py         # Portfolio 5% circuit breaker (every 15 min)
├── reflect_on_trade.py         # Post-trade LLM reflection → BM25 memory
├── wake_recovery.py            # MacBook sleep recovery
└── process_member_prefs.py     # Member watchlist/risk commands (every 10 min)
```

### Framework Gap Closures (vs. [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents))

| Gap | File | Description |
|-----|------|-------------|
| Gap 1 | `tradingagents/memory/situation_memory.py` | Persistent BM25 memory (JSON, 500 entries) |
| Gap 2 | `scripts/reflect_on_trade.py` | Post-trade reflection loop — LLM learns from outcomes |
| Gap 3 | `tradingagents/agents/managers/research_synthesizer.py` | Research Manager synthesis layer |
| Gap 4 | `tradingagents/graph/debate_engine.py` | Multi-round Bull/Bear debate engine |
| Gap 5 | `tradingagents/graph/signal_processor.py` | Signal extraction + standardized card formatting |

---

## Trade Execution Rules

### Entry Thresholds
| Window | Score | Conviction |
|--------|-------|-----------|
| 9:30 AM – 1:00 PM | ≥ 7.0 | ≥ 7 |
| 1:00 PM – 2:30 PM | ≥ 7.5 | ≥ 8 |
| After 2:30 PM | ❌ No new entries | — |

### Risk Parameters
- **Stop loss:** -3% | **Take profit:** +8%
- **Max open positions:** 2
- **Kelly sizing:** half-Kelly from rolling 30-trade win rate (floor: 1%)
- **Drawdown halt:** portfolio down 5%+ → no new entries
- **Guru bonus:** injected before gate check (can push score over threshold)

### Gate Sequence (`trade_gate.py`)
1. Drawdown state check (`logs/drawdown_state.json`)
2. Market hours validation
3. Individual circuit breaker
4. Earnings proximity filter (warn only)
5. Correlation filter (max 2 correlated positions)
6. Kelly position sizing calculation
7. VWAP advisory (non-blocking)
8. Guru bonus injection (`logs/guru_signals.json`)
9. Bracket order execution via Alpaca

---

## Guru Tracker

Monitors 10 top hedge fund managers + 5 politicians for new positions.

### Hedge Funds
| Manager | Fund | Alpha |
|---------|------|-------|
| Druckenmiller | Duquesne | 0.9 |
| Tepper | Appaloosa | 0.8 |
| Burry | Scion | 0.8 |
| Buffett | Berkshire | 0.7 |
| Ackman | Pershing Square | 0.75 |
| Cohen | Point72 | 0.7 |
| Dalio | Bridgewater | 0.6 |
| Halvorsen | Viking | 0.7 |
| Loeb | Third Point | 0.65 |
| Coleman | Tiger Global | 0.65 |

### Politicians
| Name | Chamber | Alpha | Notes |
|------|---------|-------|-------|
| Nancy Pelosi | House | 0.95 | Tech options — copy immediately |
| Tommy Tuberville | Senate | 0.7 | Financials/energy |
| Dan Crenshaw | House | 0.65 | Defense (LMT/RTX/NOC) |
| Rand Paul | Senate | 0.6 | Pharma shorts |

### Score Bonuses (injected before gate check)
| Trigger | Bonus |
|---------|-------|
| Pelosi / Druckenmiller new position | +0.9 |
| Tepper / Burry new long | +0.8 |
| Buffett / Ackman new position | +0.7 |
| Cohen / Halvorsen new position | +0.7 |
| Generic congressional buy | +0.4 |
| Insider cluster buy (3+) | +0.6 |
| CEO buy $500k+ | +0.7 |

---

## Breaking News Monitor

Runs every 2 minutes, 24/7. Posts to Discord only on fresh, actionable news.

- **Sources:** 20 RSS feeds + Finnhub (10 tickers) with 4-minute dedup window
- **Hard rule:** Market moves NEVER trigger posts — only fresh news headlines do
- **Dedup TTL:** 4 hours

### Tier Routing
| Tier | Trigger | Channels |
|------|---------|----------|
| TIER 1 | War / Fed / Hormuz closure | #breaking-news + #war-room + TTS |
| TIER 2 | Earnings / M&A / FDA / Congressional buy | #breaking-news + #war-room |
| VIP Guru | Pelosi / Druckenmiller | Both channels |
| Silent | Nothing actionable | No post |

---

## Cron Schedule

### 24/7
| Job | Schedule |
|-----|----------|
| Breaking News Monitor | Every 2 min |
| Iran Suppressor Refresh | Every 3h (silent) |
| HQ Member Onboarding | Every 5 min |
| Trading Private Channels | Every 5 min |
| Member Prefs Handler | Every 10 min |

### Pre-Market (Weekdays)
| Job | Time |
|-----|------|
| Guru Tracker | 6:00 AM ET |
| FOMC Monitor | 8:00 AM ET |
| Sentiment Aggregator | 8:00 AM ET |
| Short Interest + ETF Flows | 8:00 AM ET (Mon only) |
| SOFR Monitor | 9:00 AM ET |
| Economic Calendar | Hourly 9–4 PM ET |
| Monday War Room Brief | 8:45 AM ET (Mon only) |
| Market Keep-Awake | 9:20 AM ET |
| Circuit Breaker Reset | 9:25 AM ET |

### Intraday
| Job | Time |
|-----|------|
| Market Scan | 9:30 AM ET → `full_pipeline_scan.py` |
| Market Scan | 10:30 AM ET → `full_pipeline_scan.py` |
| Market Scan | 12:00 PM ET → `full_pipeline_scan.py` |
| Market Scan | 1:00 PM ET (score ≥7.5) |
| Market Scan | 2:30 PM ET (score ≥7.5, conv ≥8) |
| Dark Pool Monitor | Every 30 min 9–4 PM |
| Drawdown Circuit Breaker | Every 15 min 9–4 PM |

### After-Hours
| Job | Time |
|-----|------|
| Earnings Calendar | 4:00 PM ET |
| Market Close P&L | 4:05 PM ET |
| After-Hours Earnings | 4–8 PM ET |
| Whale Tracker | Every 4h |
| Overnight Futures | 11 PM / 2 AM / 5 AM ET |

### Weekly
| Job | Time |
|-----|------|
| Sunday Futures Monitor | Sun 6:05 PM ET |

---

## Member Private Channels

Private trading channels for each server member. Each member gets:
- A private `#{username}-trades` channel visible only to them and the owner
- Real-time trade alerts when Cooper takes a position on their watchlist tickers
- Personalized responses with live data (never cached/stale prices)

### Preference Commands
Message your private channel:
```
watchlist: NVDA, AAPL, MSFT    → sets tickers to watch
risk: conservative              → conservative / moderate / aggressive
```

---

## Dashboard

Real-time SSE dashboard at `http://localhost:8002` (5-page SPA):
- **Portfolio** — P&L, open positions, bracket orders
- **Signals** — Live signal cards with ASCII charts
- **Options** — Multi-strategy options engine (9 strategies)
- **Intelligence** — Guru signals, whale activity, sentiment scores
- **Backtest** — Historical performance analytics

---

## Setup

### Prerequisites
```bash
python3 -m pip install -r requirements.txt
```

### Environment Variables (`.env`)
```env
# Required
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Data sources
FINNHUB_API_KEY=your_key
ALPHA_VANTAGE_KEY=your_key
POLYGON_API_KEY=your_key
NEWS_API_KEY=your_key

# Optional (graceful degradation if missing)
WEBULL_EMAIL=
WEBULL_PASSWORD=
WEBULL_TRADING_PIN=
```

### Run a Quick Quote
```bash
python3 scripts/quick_quote.py NVDA MSFT AAPL
```

### Run Full Pipeline Scan
```bash
python3 scripts/full_pipeline_scan.py --ticker NVDA --rounds 2
```

### Run Trade Gate (manual test)
```bash
python3 scripts/trade_gate.py \
  --ticker NVDA \
  --action BUY \
  --score 7.8 \
  --conviction 8 \
  --analysis "Strong breakout above VWAP" \
  --scan-time "9:30"
```

### Start Dashboard
```bash
python3 dashboard/server.py
# Open http://localhost:8002
```

---

## Architecture Rules (Inviolable)

1. **Market moves NEVER generate Discord posts** — only fresh RSS/Finnhub headlines do
2. **No web searches from the market moves path** in the breaking news monitor
3. **`openclaw oracle` does not exist** — use `claude --print --model claude-sonnet-4-6`
4. **All scripts:** `REPO = Path(__file__).resolve().parent.parent` before `sys.path.insert`
5. **Graceful degradation** on all API failures (try/except everywhere)
6. **SQLite only** — `sqlite3` stdlib, no new DB dependencies
7. **Dedup TTL = 4h** | Iran war suppressors refresh every 3h
8. **Reflection is async** (`Popen`, not `run`) — never blocks `close_position.py`
9. **Guru bonus injects before gate check** — can legitimately push score over threshold
10. **Live data always** — never answer market questions from training knowledge
11. **Member data sealed** — private channel data never crosses channel boundaries

---

## $1M Math

| Metric | Value |
|--------|-------|
| Starting capital | $100,394 |
| Target | $1,000,000 |
| Avg win | 12% |
| Win rate | 65% |
| Trades needed | ~682 |
| Scans/day | 5 |
| Trading days/year | 250 |
| **Estimated timeline** | **< 2 years** |

---

## Forked From

[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — extended with:
- 5 framework gap closures (BM25 memory, reflection loop, research synthesis, multi-round debate, signal processor)
- 12 new intelligence modules
- Native OpenClaw integration (no separate API keys)
- Private member channel system
- 24/7 breaking news monitor
- Guru tracker (hedge funds + politicians)
- Full SSE real-time dashboard

---

*Built with [OpenClaw](https://openclaw.ai) | Cooper 🦅 | Last updated: 2026-03-01*
