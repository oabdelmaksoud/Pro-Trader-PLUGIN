# Trading Recovery Plan — $500 to Full Recovery

> **Current situation:** ~$2,137 total across accounts (~$572 investable in Robinhood Investing, $0.18 in Short Term, $1,565 in Banking). Combined all-time loss: ~$51,737 (96%).
>
> **Investable capital:** ~$500-572
>
> **Goal:** Recover losses methodically while protecting remaining capital

---

## Hard Rules (Non-Negotiable)

1. **Never risk more than 2% of account on a single trade** — With $500 that's $10 max loss per trade
2. **Only take A+ setups** — Score >= 8.0, Conviction >= 8 (raised from 7.0/7)
3. **One position at a time** until account reaches $1,000
4. **Always use stop losses** — No exceptions, no "holding and hoping"
5. **No revenge trading** — If you lose 3% in a day, stop trading for the day
6. **No options until account is above $2,000** — Options likely caused the 99.99% loss in Short Term
7. **No leveraged ETFs (SOXL, TQQQ)** until account is above $5,000
8. **Cash account only** — No margin. You cannot afford a margin call

---

## Phase 1: Survival ($500 → $1,000)

**Timeline:** 4-8 weeks | **Risk per trade:** 1-2% ($5-10)

### Strategy
- **Trade only the highest-conviction setups** from ProTrader scans (score 8+)
- **Focus on shares, not options** — Buy 1-5 shares of quality stocks
- **Target 2:1 reward-to-risk minimum** — Risk $10 to make $20
- **Day trade or next-day swing only** — Don't hold overnight unless thesis is rock solid
- **Max 1 trade per day** — Quality over quantity

### What to trade
- Tier 1 large-caps with clear catalysts (NVDA, AAPL, META on earnings/events)
- SPY/QQQ on clear trend days with volume confirmation
- Avoid: penny stocks, meme stocks, anything with spread > 0.5%

### Key metrics to track
- Win rate (target: 55%+)
- Average win vs average loss (target: 2:1+)
- Max consecutive losses (if 3 in a row, pause 1 full day)

---

## Phase 2: Growth ($1,000 → $5,000)

**Timeline:** 2-4 months | **Risk per trade:** 2% ($20-100)

### Strategy
- **Increase position size gradually** — Still 1-2 positions max
- **Start allowing swing trades** (2-5 day holds) on strong trends
- **Use ProTrader's full pipeline** — debate engine + all agents
- **Begin tracking guru signals** for conviction boosts
- Score threshold can relax to 7.5 with conviction 8

### What to add
- Slightly larger positions (up to 15% of account per trade)
- Sector momentum plays when ProTrader macro agent confirms trend

---

## Phase 3: Acceleration ($5,000 → $25,000)

**Timeline:** 3-6 months | **Risk per trade:** 2% ($100-500)

### Strategy
- **Allow 2 concurrent positions**
- **Can use simple options** (buying calls/puts only, no selling, no spreads)
- **Options rules:** Only buy with 30+ DTE, delta > 0.5, risk max 5% of account
- **Enable trailing stops** at 2% after 1.5% gain
- Score threshold returns to default 7.0/7

---

## Phase 4: Full Recovery ($25,000 → $53,874)

**Timeline:** 3-6 months

### Strategy
- **Standard ProTrader operations** — Full strategy config
- **Allow multi-leg options** if proven profitable in Phase 3
- **Kelly sizing engaged** — by now you have enough trade history for real Kelly
- **Max 2-3 positions**, conviction-scaled sizing

---

## What Went Wrong (Based on Your Screenshots)

| Account | Loss | Likely Cause |
|---|---|---|
| Robinhood Investing | -$48,391 (98.83%) | Concentrated positions, likely held losers too long, no stops |
| Short Term | -$2,734 (99.99%) | Options trading with too much size, likely 0DTE or weeklies |
| Overall Portfolio | -$51,737 (96.03%) | Combination of oversizing, no risk management, revenge trading |

### The pattern that caused this:
1. Take a large position (probably 20-50%+ of account)
2. It goes against you
3. Hold hoping it recovers (no stop loss)
4. It gets worse, maybe average down
5. Eventually forced to sell at massive loss or options expire worthless
6. Try to "make it back" with an even bigger bet
7. Repeat until 96% gone

**This pattern must end today.**

---

## OpenClaw + ProTrader Setup Checklist

- [x] SKILL.md created for OpenClaw registration
- [x] Strategy.json recalibrated for $500 account
- [x] Score thresholds raised (8.0/8 instead of 7.0/7)
- [x] Max positions reduced to 1
- [x] Account floor set to $400 (hard stop)
- [x] VIX high regime = 0% size (don't trade in chaos)
- [x] Hardcoded paths fixed in scan_run.py
- [x] Model config fixed (Claude Opus/Sonnet instead of GPT)
- [x] State files reset to $500 baseline
- [x] Kelly params set to conservative defaults

### Still needed from you:
1. **Set your Alpaca API keys** in `.env` (copy from `.env.example`)
2. **Set your Finnhub API key** for news monitoring
3. **Install the skill in OpenClaw** — copy this repo to your OpenClaw skills directory
4. **Test with paper trading first** — Run at least 20 paper trades before using real money
5. **Review every trade ProTrader suggests** — Don't blindly follow, use it as analysis support

---

## Daily Routine

1. **Pre-market (8:30-9:15 AM ET):** Run ProTrader scan, review breaking news, check futures
2. **Market open (9:30-10:00 AM):** Wait 30 min for volatility to settle. Do NOT trade the open
3. **Mid-morning (10:00-11:30 AM):** Best window for entries. Run debate engine on top candidates
4. **Midday (11:30-1:00 PM):** Low volume. Manage existing positions only
5. **Afternoon (1:00-3:00 PM):** Second-best entry window. New scans
6. **Last hour (3:00-3:45 PM):** Close all day trades. Review P&L
7. **Post-market:** Run ProTrader reflection if any trades closed. Update memory

---

## Math Reality Check

Starting from $500, here's what consistent +2% average weekly returns look like:

| Week | Balance | | Week | Balance |
|---|---|---|---|---|
| 4 | $541 | | 26 | $839 |
| 8 | $586 | | 39 | $1,084 |
| 12 | $634 | | 52 | $1,398 |
| 16 | $686 | | 78 | $2,325 |
| 20 | $743 | | 104 | $3,868 |

At 2% weekly compounding, it takes about **2.5 years** to reach $53K. That's the math.

To go faster, you need higher returns per trade — but higher returns mean higher risk, and higher risk is what destroyed the account. **There is no shortcut that doesn't also carry the risk of losing the remaining $500.**

The realistic path: Compound slowly, protect capital, let ProTrader find the A+ setups, and NEVER break the hard rules above.

---

*Recovery mode activated — 2026-03-10*
