# 🦅 ProTrader — Autonomous Multi-Agent Trading System

> **Target:** $1,000,000 from $100,499 · Paper trading via Alpaca · Zero manual steps · Built on OpenClaw

[![CI](https://img.shields.io/badge/CI-8%2F8%20passing-brightgreen)](https://github.com/oabdelmaksoud/protrader)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![Agents](https://img.shields.io/badge/agents-7%20active-purple)](https://github.com/oabdelmaksoud/protrader)
[![News](https://img.shields.io/badge/news%20scan-every%202%20min-orange)](https://github.com/oabdelmaksoud/protrader)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What Is This?

ProTrader is a **fully autonomous trading system** that runs 24/7 on a Mac. It:

- 🔍 **Scans markets 5× per day** using 7 specialized AI agents in parallel
- 📡 **Monitors breaking news every 2 minutes** — macro events + stock-specific catalysts, 24/7
- 🧠 **Debates every trade** using a Bull vs Bear multi-round argument engine (2 rounds)
- 🚦 **Gates every entry** through 9 risk checkpoints before touching Alpaca
- 📊 **Posts real-time signals** to Discord with standardized signal cards + ASCII charts
- 🔄 **Learns from every trade** via post-trade LLM reflection and BM25 persistent memory
- 👥 **Serves private member channels** — personal alerts, portfolio analysis, live quotes
- 🐋 **Tracks whales** — congressional trades, insider Form 4 filings, unusual options flow
- 🧙 **Follows guru alpha** — 10 hedge fund managers + 5 politicians → score bonuses

No separate LLM API keys needed. All inference routes through OpenClaw's native model routing.

---

## Architecture

### Full Trading Pipeline

```mermaid
flowchart TD
    CRON["⏰ Cron Scheduler\n5× daily + 24/7 monitors"] --> COOPER["🦅 Cooper\nOrchestrator"]

    COOPER --> DATA["📊 get_market_data.py\n15+ sources · pure data · no LLM"]
    COOPER --> GURU["🧠 guru_tracker.py\n13F + STOCK Act + GuruFocus RSS"]
    COOPER --> BNM["📡 breaking_news_monitor.py\nstandalone · rule-based · no session context"]

    DATA --> PIPELINE["🔄 full_pipeline_scan.py\nwires all 5 gap-closure modules"]
    GURU --> GSIG["logs/guru_signals.json\nbonus scores by ticker + action"]

    PIPELINE --> FLASH["📈 Flash\nTechnical Analysis\nMACD · BB · VWAP · RSI"]
    PIPELINE --> MACRO["🌍 Macro\nFundamentals + News\nEarnings · Sector · BTC"]
    PIPELINE --> PULSE["💬 Pulse\nSentiment + Options Flow\nFinBERT · GEX · Dark Pool"]

    FLASH --> SYNTH["🔮 research_synthesizer.py\nResearch Manager · Gap 3\nClaude Sonnet synthesis"]
    MACRO --> SYNTH
    PULSE --> SYNTH

    SYNTH --> BM25["🧩 situation_memory.py\nBM25 Memory Lookup · Gap 1\nlogs/situation_memory.json · 500 entries"]
    BM25 --> DEBATE["⚔️ debate_engine.py\nBull 🐂 vs Bear 🐻 · 2 Rounds · Gap 4\nClaude Opus researchers"]
    DEBATE --> SIGPROC["⚡ signal_processor.py\nSignal Extraction + Scoring · Gap 5"]

    SIGPROC --> INTEL["📦 Intelligence Context Loader\nguru bonuses + sentiment + short interest"]
    GSIG --> INTEL

    INTEL --> GATE["🚦 trade_gate.py\nGates 1–9 · Kelly Sizing · Drawdown Check\nguru bonus injects BEFORE gate check"]

    GATE -->|"score ≥ 7.0 · conviction ≥ 7"| ORDER["📋 Alpaca Bracket Order\nstop: -3% · target: +8%\nmax 2 positions · Kelly-sized"]
    GATE -->|"score < threshold"| SKIP["⏭️ Skip · Discord silent"]

    ORDER --> DISCORD["📣 Discord Signal Card\n#paper-trades + #war-room\nASCII chart · TradingView link"]
    ORDER --> CLOSE["🔒 close_position.py\noutcome logging · sidecar cleanup"]
    CLOSE --> REFLECT["🪞 reflect_on_trade.py\nPost-Trade Reflection · Gap 2\nasync Popen · non-blocking"]
    CLOSE --> CALIBRATE["📐 position_calibrator.py\nRolling Kelly Update\nasync Popen · non-blocking"]

    REFLECT --> MEMORY["💾 logs/situation_memory.json\nBM25 store · 500 entries max"]
    CALIBRATE --> KELLY["📁 logs/kelly_params.json"]

    BNM --> TIER{"Tier\nClassifier\nrule-based Python"}
    TIER -->|"TIER 1: war/Fed/Hormuz"| WR1["#breaking-news + #war-room"]
    TIER -->|"TIER 2: earnings/FDA"| WR2["#breaking-news + #war-room"]
    TIER -->|"TIER 3: analyst/data"| WR3["#breaking-news only"]
    TIER -->|SILENT| NULL["no post"]

    style COOPER fill:#1a1a2e,color:#fff
    style GATE fill:#16213e,color:#fff
    style DEBATE fill:#0f3460,color:#fff
    style ORDER fill:#533483,color:#fff
    style BNM fill:#1a3a2e,color:#fff
```

---

### Breaking News Monitor (Standalone Script Architecture)

> **Why standalone?** The previous inline LLM cron session accumulated 191k tokens of context over 90 minutes and crashed during live war coverage. The new architecture runs a fresh Python process every 2 minutes — zero session context, zero overflow risk.

```mermaid
flowchart TD
    CRON["⏰ Cron: every 2 minutes\ngemini-2.0-pro-exp · 240s timeout\nCron ID: 081e1c4f"] --> EXEC["exec: python3 scripts/breaking_news_monitor.py"]

    EXEC --> DEDUP["Load logs/news_dedup.json\n4-hour TTL · corruption-hardened\nrejects non-float timestamps"]

    DEDUP --> RSS["🗞️ Scan 20 RSS Feeds\n4-minute freshness window"]
    DEDUP --> FIN["📊 Scan Finnhub API\n10 macro tickers\n4-minute freshness window"]

    RSS --> CLASSIFY["Rule-Based Tier Classifier\nno LLM · instant · zero tokens"]
    FIN --> CLASSIFY

    CLASSIFY -->|TIER 1| T1["🚨 #breaking-news + #war-room\nWar · military strikes · supreme leader · Fed emergency\nHormuz closure · nuclear · default · market halt"]
    CLASSIFY -->|TIER 2| T2["⚡ #breaking-news + #war-room\nEarnings surprise · M&A · FDA · congressional buy\ninsider trade · activist · short squeeze · rate decision"]
    CLASSIFY -->|TIER 3| T3["📰 #breaking-news only\nAnalyst call · product launch · economic data · IPO"]
    CLASSIFY -->|SILENT| SL["No post\nSports · opinion · analysis · explainers"]

    T1 --> SAVE["Update dedup cache\nSave logs/news_dedup.json"]
    T2 --> SAVE
    T3 --> SAVE

    RSS_FEEDS["Reuters · CNBC · Bloomberg · MarketWatch\nWSJ · FT · NYT · Al Jazeera · Fox News\nNasdaq · Seeking Alpha · SEC EDGAR\nFDA · Sky News · Fox Business · WashPost\n+ MW Bulletins + Economist + DJ Markets"] --> RSS
    TICKERS["NVDA · MSFT · AAPL · GOOGL · META\nAMZN · AMD · TSLA · SPY · QQQ"] --> FIN

    style EXEC fill:#1a3a2e,color:#fff
    style CLASSIFY fill:#16213e,color:#fff
```

---

### Trade Gate Sequence (9 Gates)

```mermaid
sequenceDiagram
    participant S as full_pipeline_scan / news_trade_trigger
    participant G as trade_gate.py
    participant K as Kelly Sizer
    participant A as Alpaca API
    participant D as Discord

    S->>G: score=7.8, conviction=8, ticker=NVDA, scan_time="10:30"

    Note over G: Gate 1 — Drawdown halt check
    G->>G: portfolio_drawdown < 5% ✅

    Note over G: Gate 2 — Market session
    G->>G: 9:30 AM–2:30 PM ET window ✅

    Note over G: Gate 3 — Circuit breaker
    G->>G: no consecutive losses on NVDA ✅

    Note over G: Gate 4a — Earnings proximity
    G->>G: no earnings within 3 days ✅

    Note over G: Gate 4b — Correlation filter
    G->>G: < 2 open positions, not correlated ✅

    Note over G: Gate 4c — Sector concentration
    G->>G: not over-weighted in tech ✅

    Note over G: Gate 4d — VIX stress filter
    G->>G: VIX within normal range ✅

    G->>K: Gate 5 — Kelly sizing
    K-->>G: half-Kelly = 4.2% of portfolio

    Note over G: Gate 6 — VWAP advisory (non-blocking)
    G->>G: price above VWAP → log limit suggestion

    Note over G: Gate 7 — Guru bonus injection
    G->>G: load logs/guru_signals.json for NVDA
    G->>G: bonus = alpha_score × action_multiplier
    G->>G: final_score = 7.8 + 0.90 = 8.7

    G->>A: Gate 8 — Submit bracket order
    Note over A: stop=-3%, take_profit=+8%, partial=50% at +5%
    A-->>G: order_id confirmed

    Note over G: Gate 9 — Sidecar writes
    G->>G: write .score, .conviction, .signal_id files

    G->>D: Signal card → #paper-trades + #war-room
```

---

### Intelligence Score Composition

```mermaid
graph TD
    BASE["Base Score\nFlash 📈 + Macro 🌍 + Pulse 💬\nweighted average · 0–10 scale"] --> SYNTH["Research Manager Synthesis\nclaude-sonnet-4-6\nresolved contradictions + confidence band"]

    SYNTH --> BM25R["BM25 Memory Retrieval\nTop-3 similar past situations\npast_outcome adjustment ±0.5"]

    BM25R --> DEBATE["Bull 🐂 vs Bear 🐻 Debate\nRound 1: opening arguments\nRound 2: rebuttals\nFinal: claude-opus-4-6 judges"]

    DEBATE --> SCORE["Debate-Adjusted Score"]

    SCORE --> BONUSES["Intelligence Bonuses\n(applied before gate check)"]

    G["🧠 Guru Signal Bonus\nformula: alpha_score × action_multiplier\ncap: 0.95\nElite (≥0.85): VIP tag → #breaking-news\nHigh (≥0.70): standard bonus\nMid (≥0.55): smaller bonus"]
    SE["💬 Sentiment Bonus\nbullish >0.5 → +0.3\nneutral → ±0\nbearish <-0.5 → -0.3"]
    SH["📉 Short Interest Bonus\nfloat >20% → +0.5 (squeeze setup)\nfloat >40% → +0.8"]
    NW["📰 News Catalyst Bonus\nCATALYST_A (EPS beat/FDA/M&A) → +1.2\nCATALYST_B (upgrade/partner) → +0.6"]
    EB["📅 Earnings Proximity\nwithin 3 days → BLOCK (Gate 4a)\nbeyond 3 days → no effect"]

    G --> BONUSES
    SE --> BONUSES
    SH --> BONUSES
    NW --> BONUSES

    BONUSES --> FINAL["Final Score\ncapped at 10.0"]

    FINAL -->|"≥7.0 · conviction≥7\n9:30 AM–1:00 PM"| ENTER["✅ Enter Trade"]
    FINAL -->|"≥7.5 · conviction≥8\n1:00 PM–2:30 PM"| ENTER
    FINAL -->|"≥7.5 · conviction≥8\nextended hours"| ENTER
    FINAL -->|"< threshold or after 2:30 PM"| PASS["⏭️ No Trade"]

    style ENTER fill:#27ae60,color:#fff
    style PASS fill:#e74c3c,color:#fff
    style BONUSES fill:#16213e,color:#fff
```

---

### Guru Tracker Pipeline

```mermaid
flowchart TD
    GCRON["⏰ Cron: 6 AM ET weekdays\nCron ID: f7be4637"] --> GT["scripts/guru_tracker.py"]

    GT --> TDJ["data/top_traders.json\naction_multipliers + alpha_tiers\nno hardcoded score values"]

    subgraph SOURCES["Data Sources"]
        F13["SEC EDGAR 13F Filings\nquarterly hedge fund positions"]
        F4["SEC Form 4\ninsider buy/sell disclosures"]
        STOCK["STOCK Act RSS\ncongressional trade disclosures"]
        GF["GuruFocus RSS\nguru news + commentary"]
    end

    SOURCES --> GT

    GT --> FORMULA["compute_bonus(alpha_score, action, profiles)\nbonus = alpha_score × action_multiplier\ncap at 0.95\n\nget_alpha_tier(alpha_score)\nelite ≥0.85 · high ≥0.70 · mid ≥0.55"]

    FORMULA --> GSIG["logs/guru_signals.json\n{ticker, bonus, action, manager, tier, timestamp}"]

    subgraph MULTIPLIERS["Action Multipliers (from top_traders.json)"]
        NP["new_position → ×1.0"]
        AP["added_to_position → ×0.75"]
        TR["trimmed → ×−0.30"]
        CL["closed → ×−0.50"]
        CP["congressional_purchase → ×1.0"]
        CS["congressional_sale → ×−0.40"]
        IB["insider_ceo_buy_500k_plus → ×0.85"]
        CB["insider_cluster_buy_3plus → ×0.75"]
        TF["three_funds_added_same_quarter → ×0.80"]
        AL["activist_letter_filed → ×0.90"]
    end

    GSIG --> GATE["trade_gate.py\nbonus injected before gate check\ncan push marginal score over threshold"]

    style FORMULA fill:#16213e,color:#fff
    style GSIG fill:#1a3a2e,color:#fff
```

---

### Ticker News Scanner (Parallel Monitor)

```mermaid
flowchart LR
    TNS_CRON["⏰ Cron: every 30 min\nmarket hours + extended"] --> TNS["scripts/ticker_news_scanner.py\n20 watchlist tickers"]

    TNS --> FINN["Finnhub company-news API\nper-ticker · 4-min window"]

    FINN --> L1["Layer 1: Keyword Regex\ninstant · free · ~85% accuracy"]

    L1 -->|CATALYST_A match| CA["Catalyst A confirmed\n+1.2 score boost"]
    L1 -->|CATALYST_B match| CB["Catalyst B confirmed\n+0.6 score boost"]
    L1 -->|ambiguous| AMB["Layer 2: LLM Verify\nclaude-haiku · ~50 tokens\n~5–15 calls/day"]
    L1 -->|CATALYST_C| LOG["Log only\nno trade trigger"]

    AMB -->|BULLISH + MAJOR| CA
    AMB -->|BULLISH + MINOR| CB
    AMB -->|NEUTRAL/BEARISH| LOG

    CA --> ROUTER["Session-Aware Router"]
    CB --> ROUTER

    ROUTER -->|"9:30 AM–4 PM ET"| REG["trade_gate.py\nnormal rules"]
    ROUTER -->|"4–9:30 AM ET"| PRE["trade_gate.py\nextended_hours=True\nspread warning logged"]
    ROUTER -->|"4–8 PM ET"| AH["trade_gate.py\nextended_hours=True\nvolume warning logged"]
    ROUTER -->|"24/7 (crypto)"| CRYPTO["MSTR · COIN · RIOT · MARA\nalways trigger"]
    ROUTER -->|"overnight/closed"| OVN["#war-room pre-position alert\nfor next open · never silent-dropped"]

    REG --> NTT["news_trade_trigger.py\nboosted score → trade_gate.py"]
    PRE --> NTT
    AH --> NTT

    style L1 fill:#16213e,color:#fff
    style ROUTER fill:#1a3a2e,color:#fff
```

---

### System Monitor Schedule

```mermaid
gantt
    title ProTrader Daily Schedule (Eastern Time)
    dateFormat HH:mm
    axisFormat %H:%M

    section 24/7 Monitors
    Breaking News Monitor (every 2 min)   :active, 00:00, 24:00
    Ticker News Scanner (every 30 min)    :active, 00:00, 24:00
    Whale Tracker (every 4 hours)         :active, 00:00, 24:00
    Iran War Suppressor Refresh (3h)      :active, 00:00, 24:00

    section Pre-Market
    Guru Tracker (13F + STOCK Act)        :done,   06:00, 06:30
    FOMC Monitor + Sentiment              :done,   08:00, 08:30
    War Room Geopolitical Brief (Mon)     :done,   08:45, 09:00
    Circuit Breaker Reset                 :done,   09:25, 09:30
    Pre-Market Gap Scanner                :done,   07:00, 09:30

    section Market Hours
    9:30 AM Full Pipeline Scan            :active, 09:30, 10:00
    10:30 AM Full Pipeline Scan           :active, 10:30, 11:00
    12:00 PM Full Pipeline Scan           :active, 12:00, 12:30
    1:00 PM Full Pipeline Scan            :active, 13:00, 13:30
    2:30 PM Final Entry Window            :crit,   14:30, 15:00
    Dark Pool Monitor                     :active, 09:30, 16:00
    Drawdown Circuit Breaker              :active, 09:30, 16:00

    section After-Hours
    Market Close P&L Report               :done,   16:05, 16:15
    After-Hours Earnings Scanner          :done,   16:00, 20:00
    Overnight Futures Monitor             :done,   22:00, 23:00
    Cipher Knowledge Synthesis            :done,   02:00, 02:30
```

---

### Post-Trade Learning Loop

```mermaid
flowchart LR
    CLOSE["close_position.py\nreads sidecars:\n.signal_id · .score · .conviction"] --> LOG["signal_db\nsqlite3 · outcome logging\nwin/loss · P&L · duration"]

    CLOSE --> RF["reflect_on_trade.py\nasync Popen\nnon-blocking"] --> MEM["situation_memory.json\nBM25 store\n500 entries max"]

    CLOSE --> PC["position_calibrator.py\nasync Popen\nnon-blocking"] --> KP["kelly_params.json\nrolling win-rate\n30-trade window"]

    MEM --> NEXT["Next Trade Scan\nBM25 retrieves top-3 similar\npast outcomes adjust score ±0.5"]
    KP --> GATE2["trade_gate.py\nhalf-Kelly from live win rate\nfloor: 1%"]

    LOG --> WT["win_rate_tracker.py\nper-ticker accuracy\nthreshold_tuner.py auto-adjusts"]
    LOG --> BACK["backtesting_engine.py\nhistorical replay\nvalidate new signals"]

    style RF fill:#1a3a2e,color:#fff
    style PC fill:#16213e,color:#fff
```

---

### Member Private Channel System

```mermaid
flowchart TD
    NM["New Server Member Joins"] --> CRON2["Auto-Provisioning Cron\nevery 5 min\nCron ID: 10c552bb"]

    CRON2 --> CREATE["Create #{username}-trades\nprivate channel\nPrivate Trading category"]
    CREATE --> PERMS["Set permissions:\n@everyone: deny all\nmember: allow 68608\nowner: allow 68608"]
    PERMS --> CONFIG["Patch openclaw.json:\nrequireMention: false\nusers allowlist: [member_id]"]

    CONFIG --> CHANNEL["Private channel active\nmember can message Cooper directly"]

    CHANNEL --> WATCHLIST["Member sets watchlist:\n'watchlist: NVDA, AAPL'\n'risk: moderate'"]
    WATCHLIST --> ALERTS["Personal trade alerts\nwhen Cooper enters on their tickers"]

    CHANNEL --> QUOTE["Market question → live quote first\nquick_quote.py TICKER\nshow price + timestamp always\nwarn explicitly if fetch fails"]

    QUOTE --> RULE["INVIOLABLE PRIVACY RULE:\nMember data is siloed\nNEVER reference one member's\nportfolio/trades in any other channel"]

    style RULE fill:#8b0000,color:#fff
    style QUOTE fill:#16213e,color:#fff
```

---

## Agent Roster

| Agent | Model | Role | When Active |
|-------|-------|------|-------------|
| Flash 📈 | claude-sonnet-4-6 | Technical analysis — MACD, BB, VWAP, RSI, sector ETF | Every scan |
| Macro 🌍 | claude-sonnet-4-6 | Fundamentals, news, economic calendar, BTC correlation | Every scan |
| Pulse 💬 | claude-sonnet-4-6 | Sentiment, options flow, GEX, dark pool, FinBERT NLP | Every scan |
| Bull 🐂 | claude-opus-4-6 | Bullish researcher — debate round 1 + rebuttal | Debate phase |
| Bear 🐻 | claude-opus-4-6 | Bearish researcher — debate round 1 + rebuttal | Debate phase |
| Risk 🛡️ | claude-sonnet-4-6 | Position sizing, correlation, drawdown, Kelly | Gate phase |
| Executor ⚡ | claude-sonnet-4-6 | Bracket orders, position monitoring, EOD close | Execution |

---

## Five Framework Gap Closures

ProTrader closes 5 gaps vs. the upstream [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) framework:

| # | Gap | File | What It Does |
|---|-----|------|--------------|
| 1 | **Persistent BM25 Memory** | `tradingagents/memory/situation_memory.py` | JSON store of past situations (500 entries max). BM25 retrieval finds top-3 analogous situations before debate. Past outcomes adjust base score ±0.5. |
| 2 | **Post-Trade Reflection** | `scripts/reflect_on_trade.py` | After each close, async LLM reflection writes lessons learned back to BM25 store. Claude Sonnet judges what went right/wrong. |
| 3 | **Research Manager Synthesis** | `tradingagents/agents/managers/research_synthesizer.py` | Resolves contradictions between Flash, Macro, Pulse before the debate. Produces confidence band and unified thesis. |
| 4 | **Multi-Round Debate Engine** | `tradingagents/graph/debate_engine.py` | Bull and Bear each argue 2 rounds (opening + rebuttal). Claude Opus adjudicates. Score adjustment applied based on debate outcome. |
| 5 | **Signal Processing Layer** | `tradingagents/graph/signal_processor.py` | Standardized extraction of trade signals from agent output. Produces structured dict consumed by trade_gate.py and discord_signal_card.py. |

---

## Guru Tracker

Monitors 10 hedge fund managers + 5 politicians. All bonuses are **formula-driven** — add any manager with an `alpha_score` and bonuses auto-derive with zero code changes.

### Bonus Formula
```
bonus = alpha_score × action_multiplier    (capped at 0.95)
```

### Action Multipliers (from `data/top_traders.json`)
| Action | Multiplier |
|--------|-----------|
| `new_position` | ×1.0 |
| `added_to_position` | ×0.75 |
| `trimmed` | ×−0.30 |
| `closed` | ×−0.50 |
| `congressional_purchase` | ×1.0 |
| `congressional_sale` | ×−0.40 |
| `insider_ceo_buy_500k_plus` | ×0.85 |
| `insider_cluster_buy_3plus` | ×0.75 |
| `three_funds_added_same_quarter` | ×0.80 |
| `activist_letter_filed` | ×0.90 |

### Alpha Tiers (from `data/top_traders.json`)
| Tier | Threshold | Tag | Action |
|------|-----------|-----|--------|
| Elite | ≥ 0.85 | `vip` | Post to #breaking-news + bonus injected |
| High | ≥ 0.70 | — | Standard bonus injected |
| Mid | ≥ 0.55 | — | Smaller bonus injected |
| Low | ≥ 0 | — | Minimal bonus |

### Tracked Managers
| Manager | Fund | Alpha Score | Example Bonus (new position) |
|---------|------|-------------|------------------------------|
| Druckenmiller | Duquesne | 0.90 | +0.90 |
| Nancy Pelosi | House | 0.95 | +0.95 |
| Tepper | Appaloosa | 0.80 | +0.80 |
| Burry | Scion | 0.80 | +0.80 |
| Ackman | Pershing Square | 0.75 | +0.75 |
| Buffett | Berkshire | 0.70 | +0.70 |
| Halvorsen | Viking Global | 0.70 | +0.70 |
| Cohen | Point72 | 0.70 | +0.70 |
| Loeb | Third Point | 0.65 | +0.65 |
| Coleman | Tiger Global | 0.65 | +0.65 |
| Tuberville | Senate | 0.70 | +0.70 |
| Crenshaw | House | 0.65 | +0.65 |
| Rand Paul | Senate | 0.60 | +0.60 |

---

## Trade Execution Rules

### Entry Thresholds
| Window | Min Score | Min Conviction | Notes |
|--------|-----------|----------------|-------|
| 9:30 AM – 1:00 PM | 7.0 | 7 | Standard window |
| 1:00 PM – 2:30 PM | 7.5 | 8 | Raised bar, afternoon slippage risk |
| After 2:30 PM | ❌ | — | No new entries |
| Extended hours | 7.5 | 8 | Wider spreads = higher bar |
| News catalyst (TIER 1/2) | 6.5 | 7 | +1.2 boost applied first, then gate |

### Risk Management
| Rule | Value |
|------|-------|
| Stop loss | −3% trailing |
| Take profit | +8% |
| Partial exit | 50% at +5%, let rest run |
| Max open positions | 2 |
| Kelly sizing | Half-Kelly from rolling 30-trade win rate |
| Kelly floor | 1% of portfolio |
| Drawdown halt | Portfolio down 5%+ → no new entries |
| Circuit breaker | 3 consecutive losses on same ticker → pause |
| Correlation filter | Blocks second position in same sector |

### Guru Bonus Injection
Bonuses inject **before** gate checks — a marginal 6.8 score + 0.9 Pelosi bonus becomes 7.7 and passes.

---

## Data Sources (15+)

| Source | Data | Access |
|--------|------|--------|
| Alpaca IEX WebSocket | Real-time quotes (primary) | API key |
| Finnhub API | News, earnings, options, company-news | API key |
| Alpha Vantage | MACD, Bollinger Bands, EMA | API key |
| Polygon.io | Options flow, tick data | API key |
| yfinance | Sector ETFs, futures, pre-market gaps | Free |
| SEC EDGAR | 13F filings, Form 4 insider trades | Free |
| House/Senate Stock Watcher | STOCK Act congressional disclosures | Free RSS |
| OpenInsider RSS | Insider cluster buys | Free |
| Finviz | Short interest (FINRA bi-weekly) | Free |
| GuruFocus RSS | Guru news signals | Free |
| NY Fed | SOFR/EFFR liquidity stress | Free |
| Earnings Whisper | EPS whisper vs. consensus | Free scrape |
| SpotGamma | GEX (gamma exposure) levels | Free |
| 20 RSS Feeds | Reuters, Al Jazeera, SEC, FDA, etc. | Free |

---

## Real-Time Discord Integration

### Channel Routing
| Channel | What Posts There |
|---------|-----------------|
| `#breaking-news` | ALL TIER 1/2/3 events from breaking news monitor |
| `#war-room` | TIER 1 + TIER 2 events + trade-actionable catalysts |
| `#paper-trades` | Every trade entry + signal card |
| `#{username}-trades` | Personal alerts when their watchlist tickers trigger |
| `#cooper-study` | Full pipeline analysis + debate transcripts |
| `#winning-trades` | Post-close wins with P&L |
| `#losing-trades` | Post-close losses with reflection summary |

### Signal Card Format
Every trade post includes:
- Ticker, direction, entry price, target, stop
- Score breakdown (base + bonuses)
- ASCII price chart (10-day)
- Options chain summary (if relevant)
- TradingView link
- Guru signal tag (if applicable)

---

## Dashboard

Real-time SSE dashboard at `http://localhost:8002` — starts automatically at 9:20 AM via LaunchAgent.

| Page | Content |
|------|---------|
| 📊 Portfolio | P&L, open positions, bracket order status, equity curve toward $1M |
| 🔔 Signals | Live signal cards with ASCII charts, score breakdowns |
| 📈 Options | Multi-strategy engine (9 strategies, 3 tabs: Directional/Income/Hedge) |
| 🧠 Intelligence | Guru signals, whale activity, sentiment scores, short interest |
| 📅 Backtest | Historical performance, win rate by ticker/time/catalyst |

---

## Quick Start

### Prerequisites
```bash
pip install feedparser requests yfinance alpaca-trade-api python-dotenv
```

### Environment (`.env`)
```env
# Required — broker
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Data sources
FINNHUB_API_KEY=your_key
ALPHA_VANTAGE_KEY=your_key
POLYGON_API_KEY=your_key
NEWS_API_KEY=your_key
```

### Usage
```bash
# Live quote (always before answering market questions)
python3 scripts/quick_quote.py NVDA MSFT AAPL

# Full data gather
python3 scripts/get_market_data.py --tickers NVDA --macro

# Run breaking news monitor manually
python3 scripts/breaking_news_monitor.py

# Run full pipeline scan
python3 scripts/full_pipeline_scan.py --ticker NVDA --rounds 2

# Manual trade gate test
python3 scripts/trade_gate.py \
  --ticker NVDA --action BUY \
  --score 7.8 --conviction 8 \
  --analysis "Strong breakout above VWAP on high volume" \
  --scan-time "9:30"

# Run guru tracker
python3 scripts/guru_tracker.py

# Check account status
python3 scripts/account_status.py

# Start dashboard
python3 dashboard/server.py  # → http://localhost:8002
```

---

## Key Cron Jobs

| Name | Schedule | ID |
|------|----------|----|
| Breaking News Monitor | Every 2 min, 24/7 | `081e1c4f` |
| Ticker News Scanner | Every 30 min | `3e8e6ce8` |
| 9:30 AM Full Scan | Weekdays 9:30 ET | `63fc0f59` |
| 10:30 AM Full Scan | Weekdays 10:30 ET | `4cd2ddbe` |
| 12:00 PM Full Scan | Weekdays 12:00 ET | `5dee7f05` |
| 1:00 PM Full Scan | Weekdays 13:00 ET | `8295fa9a` |
| 2:30 PM Final Window | Weekdays 14:30 ET | `9a0a1837` |
| Guru Tracker | 6 AM ET weekdays | `f7be4637` |
| Iran War Dedup Refresh | Every 3h | `3f56da71` |
| HQ Server Auto-Onboarding | Every 5 min | `021bb1c4` |
| Trading Private Channels | Every 5 min | `10c552bb` |

---

## System Rules (Inviolable)

1. **Market moves NEVER generate Discord posts** — only fresh news headlines trigger
2. **Live data always** — run `quick_quote.py` before answering any market question
3. **`openclaw oracle` does not exist** — use `claude --print --model <model>`
4. **REPO pattern** — all scripts: `REPO = Path(__file__).resolve().parent.parent` before `sys.path.insert`
5. **Graceful degradation** — every API call in try/except; system never crashes on failure
6. **SQLite only** — stdlib `sqlite3`, no new DB dependencies
7. **Dedup TTL = 4h** — Iran/war suppressors auto-refresh every 3h
8. **Reflection is async** — `Popen`, not `run` — never blocks position close
9. **Guru bonus injects before gate** — can legitimately push marginal score over threshold
10. **Formula-driven bonuses** — no hardcoded names in code; add any manager with `alpha_score` → bonuses auto-derive
11. **Member data sealed** — private channel data never referenced in any shared channel or session
12. **Session-aware routing** — regular/premarket/afterhours/crypto/futures/closed all handled
13. **Overnight alerts** — catalysts during closed hours post as pre-position alerts, never silently dropped
14. **Breaking news monitor = standalone Python** — never inline agentTurn (context overflow risk)
15. **Dedup corruption guard** — reject any non-float values in dedup JSON before loading

---

## $1M Math

| Metric | Value |
|--------|-------|
| Starting capital | $100,499 |
| Current portfolio | ~$100,394 |
| Target | $1,000,000 |
| Required gain | ~10× |
| Expected avg win | 12% |
| Expected win rate | 65% |
| Avg trades/day | 1–2 |
| Trading days/year | 250 |
| Estimated timeline | **< 2 years** |

---

## Commit History (Key Milestones)

| Commit | Change |
|--------|--------|
| `33e92f6` | standalone `breaking_news_monitor.py` — fixes context overflow |
| `11f5549` | formula-driven guru bonuses — `action_multipliers` + `alpha_tiers` |
| `1dd941e` | README overhaul with Mermaid diagrams |
| `fda2c8f` | `quick_quote.py` — fast live quote fetcher |
| `17f429f` | SOUL.md + CLAUDE.md live-data-first + privacy rules |
| `9799bae` | Guru Tracker module — 13F + STOCK Act tracking |
| `069831c` | All 5 TauricResearch framework gaps closed |
| `ff1a05b` | News-to-Trade bridge (`news_trade_trigger.py`) |
| `13f03e4` | Repo renamed `coopercorp-trading` → `protrader` |

---

## Built On

- [OpenClaw](https://openclaw.ai) — agent orchestration, cron scheduling, Discord integration
- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — base framework (5 gaps closed)
- [Alpaca Markets](https://alpaca.markets) — paper + live trade execution
- [Finnhub](https://finnhub.io) — real-time financial data

---

*🦅 Cooper · ProTrader · Last updated: 2026-03-01*
