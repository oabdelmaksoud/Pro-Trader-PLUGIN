<div align="center">

# 🦅 CooperCorp Trading System

### Autonomous Multi-Agent Paper Trading · Powered by OpenClaw + Alpaca

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Alpaca](https://img.shields.io/badge/Broker-Alpaca_Paper-FFCD00?logo=alpaca&logoColor=black)](https://alpaca.markets)
[![Tests](https://img.shields.io/badge/Tests-8%2F8_passing-brightgreen?logo=pytest)](tests/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![Forked from](https://img.shields.io/badge/Forked_from-TauricResearch%2FTradingAgents-orange?logo=github)](https://github.com/TauricResearch/TradingAgents)

**$100,499 → $1,000,000 · Paper trading · 24/7 autonomous · Multi-agent LLM pipeline**

</div>

---

## What Is This?

CooperCorp is a **fully autonomous paper trading system** built on top of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents). It runs 5 intraday scans per day using a debate-style multi-agent LLM pipeline, executes trades via Alpaca's paper API, monitors positions 24/7, and posts every signal and trade to Discord in real time.

> **Status:** Live and running. NVDA put opened and closed +18.8% on Week 1.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    COOPERCORP TRADING SYSTEM                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   │
│  │  Flash   │   │  Macro   │   │  Pulse   │   │ Cipher   │   │
│  │ 📈 Tech  │   │ 🌍 Fund. │   │ 💬 Sent. │   │ 🔊 News  │   │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────────┘   │
│       │              │              │                           │
│       └──────────────┴──────────────┘                          │
│                       │                                        │
│              ┌─────────▼─────────┐                            │
│              │   Bull 🐂 vs Bear 🐻  │  ← Debate / Score      │
│              └─────────┬─────────┘                            │
│                        │                                       │
│              ┌─────────▼─────────┐                            │
│              │  Risk 🛡️ Gate       │  ← 4 gates: market hours │
│              │  (trade_gate.py)   │    circuit breaker         │
│              └─────────┬─────────┘    position limit          │
│                        │              portfolio heat           │
│              ┌─────────▼─────────┐                            │
│              │  Executor ⚡       │  ← Alpaca API              │
│              │  Bracket orders   │    Stop -3% / TP +8%       │
│              └─────────┬─────────┘    Trailing stop           │
│                        │                                       │
│  ┌─────────────────────▼──────────────────────────────────┐   │
│  │              Discord · Dashboard · Logs                 │   │
│  │  #war-room  #paper-trades  #winning  #losing  #options  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Signal Pipeline

```
9:30 AM ──────────────────────────────────────────────── 2:30 PM
   │         │           │           │           │
   ▼         ▼           ▼           ▼           ▼
SCAN 1    SCAN 2      SCAN 3      SCAN 4      SCAN 5
9:30      10:30       12:00       1:00        2:30
score≥7   score≥7    score≥7    score≥7    score≥7.5
conv≥7    conv≥7     conv≥7     conv≥7     conv≥8
                                           (last window)

Each scan:
┌─────────────────────────────────────────────────────┐
│  get_market_data.py (real-time: Alpaca→Finnhub→CBOE) │
│  13 Tier 1 tickers + dynamic Tier 3 movers           │
│         │                                            │
│  Pre-score filter (≥5.5) → top candidate             │
│         │                                            │
│  5 parallel sub-agents via sessions_spawn            │
│  Flash · Macro · Pulse · Bull · Bear                 │
│         │                                            │
│  Weighted score: Catalyst 30% + Tech 25%             │
│                  Sentiment 20% + Fund 15% + RR 10%   │
│         │                                            │
│  ≥7.0 score AND ≥7 conviction → trade_gate.py       │
│         │                                            │
│  Alpaca bracket order: entry / stop-3% / tp+8%      │
└─────────────────────────────────────────────────────┘
```

---

## Data Sources

| Source | Data | Tier | Auth |
|---|---|---|---|
| **Alpaca IEX** | Real-time US equity quotes + portfolio | Live | API key |
| **Alpaca Crypto** | Real-time BTC/ETH | Live | API key |
| **CBOE CDN** | Options chains: full Greeks, IV, OI, volume | Real-time | None |
| **Finnhub** | Company news, earnings calendar, quotes | Real-time | Free key |
| **Yahoo Finance RSS** | Ticker-specific headlines | Real-time | None |
| **PR Newswire RSS** | Official press releases | Real-time | None |
| **MarketWatch RSS** | Market top stories | Real-time | None |
| **Google News RSS** | Broad financial coverage | Real-time | None |
| **NewsAPI** | 80,000+ news sources | ~Real-time | Free key |
| **Polygon.io** | Market movers, reference data | 15-min delay | Free key |
| **Alpha Vantage** | News sentiment scores | 25 req/day | Free key |
| **Stocktwits** | Retail trader sentiment | Real-time | None |
| **SEC EDGAR** | 8-K, Form 4 filings | Real-time | None |
| **Earnings Whisper** | Whisper EPS estimates | Daily | None |

**Real-time quote chain:** `Alpaca IEX → Finnhub → Polygon → Webull → yfinance`

---

## Risk Management

```
┌───────────────── RISK GATES (trade_gate.py) ──────────────────┐
│                                                                 │
│  Gate 1: Market hours (9:30–3:45 ET, Mon–Fri)                 │
│  Gate 2: Circuit breaker (daily loss > -5% → halt)            │
│  Gate 3: Earnings blackout (no entries <1 day to earnings)     │
│  Gate 4a: Position limit (max 2 simultaneous positions)        │
│  Gate 4b: Portfolio heat (max 12% total, 8% per sector)        │
│  Gate 4c: Correlation filter (no 2 positions in same group)    │
│  Gate 4d: Duplicate prevention (no re-entry same day)          │
│                                                                 │
│  Position sizing:  VIX < 20 → 1.0×  ·  VIX 20–30 → 0.7×     │
│                    VIX > 30 → 0.4×                             │
│                                                                 │
│  Exit rules:       Stop loss:    -3% (bracket at broker)       │
│                    Partial exit: +5% → close 50%               │
│                    Take profit:  +8% (bracket at broker)       │
│                    Trailing:     3% below HWM (activates +2%)  │
│                    EOD:          Force close 3:45 PM            │
│                    (except: options, swing tags)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 24/7 Monitoring Crons

```
 Mon–Fri  ──────────────────────────────────────────────────────
  4:00 AM  Pre-market extended scan
  7:00 AM  Pre-market extended scan
  8:00 AM  Macro calendar (Mon) / Morning brief
  9:15 AM  Pre-market top 3 analysis
  9:20 AM  Keep-awake + stream + dashboard START
  9:25 AM  Circuit breaker reset + system ready
  9:30 AM  ━━ SCAN 1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 10:30 AM  ━━ SCAN 2 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 11:30 AM  Position monitor
 12:00 PM  ━━ SCAN 3 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1:00 PM  ━━ SCAN 4 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  2:00 PM  Afternoon position review
  2:30 PM  ━━ SCAN 5 (last window, score≥7.5) ━━━━━━━━━━━━━━━
  3:45 PM  EOD force close
  4:05 PM  Market close P&L update
  4:20 PM  Stream + dashboard STOP

 24/7  ──────────────────────────────────────────────────────
 */30       Breaking news monitor (ALL hours)
 */30       Futures & crypto monitor → #futures-signals
 15,45      Gold / XAUUSD monitor → #gold-xauusd-signals
 11PM/2AM/5AM  Overnight macro check

 Weekly  ─────────────────────────────────────────────────────
 Sun 8PM   Sector rotation analysis
 Mon 7:30  Learning review + score adjustments
 Mon 8:00  Macro calendar (earnings + economic data)
```

---

## Discord Integration

| Channel | Purpose |
|---|---|
| `#war-room-hive-mind` | All alerts, scan results, system status |
| `#paper-trades` | Every trade entry and exit |
| `#winning-trades` | Closed winners |
| `#losing-trades` | Closed losers + lessons |
| `#options-trades` | Options signals (CBOE-sourced) |
| `#cooper-study` | Weekly analysis + sector rotation |
| `#trading-chat` | Morning brief |
| `#futures-signals` | ES/NQ/BTC/ETH 24/7 |
| `#gold-xauusd-signals` | Gold/Silver/DXY/TLT 24/7 |
| `#gamespoofer-trades` | Personal position tracking |

---

## Dashboard

Real-time SSE-powered SPA at `http://localhost:8002` — 5 pages:

```
┌──────────────────────────────────────────────────────────────┐
│  Portfolio │ Signals │ Market Intel │ Watchlist │ Analytics  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  $100,499 ──────────────────────────────── $1,000,000       │
│  ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░  10%                     │
│                                                              │
│  Live positions · Real-time P&L · Equity curve              │
│  VIX · Fear & Greed · SPY/QQQ/SMH · BTC signal             │
│  Signal feed · Options chain viewer · News feed              │
└──────────────────────────────────────────────────────────────┘
```

Start: `python3 dashboard/server.py --port 8002`

---

## Options Engine

CBOE real-time options data (no API key, no login) → 9 strategies in 3 tabs:

```
Directional          Neutral              Income
─────────────        ─────────────        ─────────────
🥇 Best call/put     ⚡ Long straddle      💰 Cash-secured put
🥈 Alt strike        🦅 Spread            📊 Covered call
🎰 Swing OTM         🔧 Iron condor
```

---

## Quickstart

```bash
git clone https://github.com/oabdelmaksoud/coopercorp-trading.git
cd coopercorp-trading

# Install dependencies
pip install -e . --break-system-packages

# Configure API keys
cp .env.example .env
# Edit .env — add Alpaca keys (required) + Finnhub (recommended)

# Verify setup
python3 -m pytest tests/ -q

# Start dashboard
python3 dashboard/server.py --port 8002
# Open http://localhost:8002

# Run a single scan manually
python3 scripts/get_market_data.py --tickers NVDA,MSFT,ARM --score --full
```

---

## Environment Variables

| Variable | Required | Source |
|---|---|---|
| `ALPACA_API_KEY` | ✅ Yes | [alpaca.markets](https://alpaca.markets) |
| `ALPACA_SECRET_KEY` | ✅ Yes | [alpaca.markets](https://alpaca.markets) |
| `ALPACA_BASE_URL` | ✅ Yes | `https://paper-api.alpaca.markets` |
| `FINNHUB_API_KEY` | Recommended | [finnhub.io](https://finnhub.io) (free) |
| `POLYGON_API_KEY` | Optional | [polygon.io](https://polygon.io) (free) |
| `NEWS_API_KEY` | Optional | [newsapi.org](https://newsapi.org) (free) |
| `ALPHA_VANTAGE_KEY` | Optional | [alphavantage.co](https://alphavantage.co) (free) |

CBOE options data requires no key. Most sources have free tiers.

---

## Project Structure

```
coopercorp-trading/
├── scripts/
│   ├── get_market_data.py      # Data layer (no LLM)
│   ├── trade_gate.py           # Execution gateway (4 gates)
│   ├── close_position.py       # Exit + learning wire-up
│   ├── futures_monitor.py      # 24/7 ES/NQ/BTC/ETH
│   ├── gold_monitor.py         # 24/7 Gold/Silver/DXY
│   ├── wake_recovery.py        # Mac sleep/wake recovery
│   └── stream_manager.py       # WebSocket start/stop
├── tradingagents/
│   ├── brokers/alpaca.py       # Broker API (paper + live)
│   ├── dataflows/
│   │   ├── cboe_options.py     # Real-time options (no key)
│   │   ├── news_aggregator.py  # 6-source news pipeline
│   │   ├── realtime_quotes.py  # Quote fallback chain
│   │   └── alpaca_stream.py    # WebSocket price feed
│   ├── risk/
│   │   ├── circuit_breaker.py  # Daily loss halt
│   │   ├── trailing_stop.py    # Dynamic stop management
│   │   ├── portfolio_heat.py   # Sector + total heat
│   │   └── trade_lock.py       # Duplicate prevention
│   ├── discord_signal_card.py  # Standardized card format
│   └── learning/
│       ├── post_mortem.py      # Per-trade analysis
│       ├── pattern_tracker.py  # Win/loss patterns
│       └── score_adjuster.py   # Dynamic threshold tuning
├── dashboard/
│   ├── server.py               # SSE backend (port 8002)
│   └── index.html              # 5-page SPA
├── config/
│   └── strategy.json           # Centralized config + watchlist
└── logs/                       # signals.jsonl · ledger.jsonl
```

---

## Week 1 Results (Feb 27, 2026)

| Trade | Type | Entry | Exit | P&L |
|---|---|---|---|---|
| `NVDA260313P00175000` | Put option | $4.43 | $3.60 | **+18.8% ✅** |

5 scans ran. ARM scored 5.5–6.9 every scan but never triggered (F&G=13 Extreme Fear, VIX ~21). System is conservative by design — no forced trades.

---

## Forked From

[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — Multi-Agents LLM Financial Trading Framework  
Paper: [arXiv:2412.20138](https://arxiv.org/abs/2412.20138)

CooperCorp extensions: live broker execution, 24/7 cron automation, real-time options (CBOE), multi-source news aggregation, SSE dashboard, OpenClaw agent integration.

---

<div align="center">
<sub>CooperCorp Trading System · PRJ-002 · Paper trading only · Not financial advice</sub>
</div>
