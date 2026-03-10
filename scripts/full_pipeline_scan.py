#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Full Pipeline Scanner
Implements ALL 5 upstream TradingAgents gaps:
  Gap 1: Persistent BM25 memory (situation_memory.py)
  Gap 2: Post-trade reflection (reflect_on_trade.py)
  Gap 3: Research Manager synthesis
  Gap 4: Multi-round Bull/Bear debate
  Gap 5: Signal processing layer

Flow:
  get_market_data → Flash/Macro/Pulse (parallel) → Research Manager (+ BM25)
  → Bull/Bear debate (N rounds) → Signal Processor → trade_gate

Usage:
  python3 scripts/full_pipeline_scan.py --ticker NVDA [--rounds 2] [--dry-run]
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv
load_dotenv(REPO / ".env")


def load_intelligence_context(repo: Path, ticker: str) -> dict:
    """Load pre-computed intelligence bonuses from daily scanners."""
    bonuses = {"score_bonus": 0.0, "reasons": [], "kelly_fraction": 0.10, "halted": False}

    # ── Drawdown halt check ──────────────────────────────────────────────────
    try:
        path = repo / "logs" / "drawdown_state.json"
        if path.exists():
            dd = json.loads(path.read_text())
            if dd.get("halted"):
                bonuses["halted"] = True
                bonuses["halt_reason"] = f"Portfolio drawdown {dd.get('drawdown_pct', '?')}% (threshold: 5%)"
    except Exception as e:
        print(f"WARN: drawdown_state load failed: {e}")

    # ── Kelly fraction (live win-rate from signal DB) ────────────────────────
    try:
        path = repo / "logs" / "kelly_params.json"
        if path.exists():
            kp = json.loads(path.read_text())
            bonuses["kelly_fraction"] = float(kp.get("half_kelly_fraction", 0.10))
            bonuses["win_rate"] = float(kp.get("win_rate", 0.60))
    except Exception as e:
        print(f"WARN: kelly_params load failed: {e}")

    # ── Guru signals (from guru_tracker.py) ─────────────────────────────────
    try:
        path = repo / "logs" / "guru_signals.json"
        if path.exists():
            data = json.loads(path.read_text())
            if ticker in data:
                bonus = float(data[ticker].get("guru_bonus", 0))
                if bonus > 0:
                    bonuses["score_bonus"] += bonus
                    reasons = data[ticker].get("reasons", [])
                    bonuses["reasons"].append(f"Guru bonus +{bonus}: {reasons[-1] if reasons else 'signal'}")
    except Exception as e:
        print(f"WARN: guru_signals load failed: {e}")

    # ── Sentiment scores (from sentiment_aggregator.py) ──────────────────────
    try:
        path = repo / "logs" / "sentiment_scores.json"
        if path.exists():
            data = json.loads(path.read_text())
            if ticker in data:
                sentiment = float(data[ticker].get("score", 0))
                if sentiment > 0.5:
                    bonuses["score_bonus"] += 0.3
                    bonuses["reasons"].append(f"Bullish sentiment +0.3 (score={sentiment:.2f})")
                elif sentiment < -0.5:
                    bonuses["score_bonus"] -= 0.3
                    bonuses["reasons"].append(f"Bearish sentiment -0.3 (score={sentiment:.2f})")
    except Exception as e:
        print(f"WARN: sentiment_scores load failed: {e}")

    # ── Short interest squeeze bonus ─────────────────────────────────────────
    try:
        path = repo / "logs" / "short_interest.json"
        if path.exists():
            data = json.loads(path.read_text())
            if ticker in data:
                short_float = float(str(data[ticker].get("short_float", "0")).replace("%", ""))
                if short_float > 20:
                    bonuses["score_bonus"] += 0.5
                    bonuses["reasons"].append(f"Squeeze setup +0.5 (short float={short_float:.1f}%)")
    except Exception as e:
        print(f"WARN: short_interest load failed: {e}")

    # ── FOMC proximity risk ──────────────────────────────────────────────────
    try:
        path = repo / "logs" / "fomc_state.json"
        if path.exists():
            fomc = json.loads(path.read_text())
            days = fomc.get("days_until_next")
            if days is not None and days <= 2:
                bonuses["score_bonus"] -= 0.5
                bonuses["reasons"].append(f"FOMC in {days} days — volatility risk -0.5")
            elif days is not None and days <= 5:
                bonuses["score_bonus"] -= 0.2
                bonuses["reasons"].append(f"FOMC in {days} days — caution -0.2")
    except Exception as e:
        print(f"WARN: fomc_state load failed: {e}")

    # ── Dark pool accumulation signal ──────────────────────────────────────
    try:
        path = repo / "logs" / "dark_pool_cache.json"
        if path.exists():
            dp = json.loads(path.read_text())
            if ticker in dp:
                block_count = dp[ticker].get("block_trades_today", 0)
                if block_count >= 5:
                    bonuses["score_bonus"] += 0.4
                    bonuses["reasons"].append(f"Dark pool: {block_count} block trades +0.4")
                elif block_count >= 3:
                    bonuses["score_bonus"] += 0.2
                    bonuses["reasons"].append(f"Dark pool: {block_count} block trades +0.2")
    except Exception as e:
        print(f"WARN: dark_pool_cache load failed: {e}")

    return bonuses


def run_agent(agent_id: str, prompt: str, timeout: int = 90) -> str:
    """Run an agent via openclaw oracle and return its output."""
    result = subprocess.run(
        ["claude", "--print", "--model",
         "claude-opus-4-6" if agent_id in ("bull", "bear") else "claude-sonnet-4-6",
         prompt],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO)
    )
    return result.stdout.strip() if result.returncode == 0 else f"[{agent_id} error: {result.stderr[:100]}]"


def gather_market_data(ticker: str) -> dict:
    """Step 1: Get raw market data and pre-score."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "get_market_data.py"),
         "--tickers", ticker, "--score", "--full", "--json"],
        capture_output=True, text=True, timeout=90, cwd=str(REPO)
    )
    try:
        for line in reversed(result.stdout.splitlines()):
            if line.strip().startswith("{"):
                return json.loads(line.strip())
    except Exception:
        pass
    return {"ticker": ticker, "score": 5.0, "raw": result.stdout[:1000]}


def _get_mtf_summary(ticker: str) -> str:
    """Get multi-timeframe confluence score if candle data exists."""
    try:
        from tradingagents.technical.mtf_analyzer import MTFAnalyzer
        analyzer = MTFAnalyzer()
        # Load from persisted candle data (built by watchdog)
        result = analyzer.analyze(ticker)
        if result.get("total_tfs", 0) > 0:
            return result.get("summary", "")
    except Exception:
        pass
    return ""


def _build_intel_context(data: dict) -> str:
    """Build intelligence context string from monitor outputs + new data sources."""
    parts = []

    # Futures contract context (if applicable)
    if data.get("asset_type") == "futures":
        fc = data.get("futures_context", "")
        if fc:
            parts.append(f"--- FUTURES CONTRACT ---\n{fc}")
        spec = data.get("contract_spec", {})
        if spec:
            parts.append(f"Margin: ${spec.get('margin', '?')} | Point Value: ${spec.get('point_value', '?')} | Asset Class: {spec.get('asset_class', '?').upper()}")

    # Earnings whisper
    ew = data.get("earnings_whisper", {})
    if ew.get("whisper_eps") is not None:
        parts.append(f"Earnings Whisper: {ew.get('note', '')}")

    # Reddit sentiment
    reddit = data.get("reddit_sentiment", {})
    if reddit.get("mention_count", 0) > 0:
        parts.append(f"Reddit: {reddit['mention_count']} mentions, sentiment={reddit.get('sentiment','?')}, hot_score={reddit.get('hot_score',0)}")

    # Monitor signals
    monitors = data.get("monitor_signals", {})
    dp = monitors.get("dark_pool", {})
    if dp:
        parts.append(f"Dark Pool: {json.dumps(dp)[:150]}")
    whale = monitors.get("whale_activity", {})
    if whale:
        parts.append(f"Whale Activity: {json.dumps(whale)[:150]}")
    etf = monitors.get("etf_flows", {})
    if etf:
        parts.append(f"ETF Flows: {json.dumps(etf)[:200]}")
    fomc = monitors.get("fomc", {})
    if fomc.get("days_until_next") is not None:
        parts.append(f"FOMC: {fomc.get('days_until_next')} days until next meeting")

    return "\n".join(parts) if parts else "No additional intelligence signals."


def run_analyst_team(ticker: str, data: dict) -> dict:
    """Step 2: Run Flash, Macro, Pulse in parallel."""
    data_summary = json.dumps({k: v for k, v in data.items()
                                if k not in ("raw", "monitor_signals", "reddit_sentiment",
                                             "earnings_whisper")}, indent=2)[:1500]

    # Build additional context from previously-unused sources
    intel_ctx = _build_intel_context(data)
    mtf_summary = _get_mtf_summary(ticker)

    mtf_block = f"\n\nMulti-Timeframe Confluence Analysis:\n{mtf_summary}" if mtf_summary else ""
    intel_block = f"\n\nIntelligence Signals:\n{intel_ctx}" if intel_ctx else ""

    is_futures = data.get("asset_type") == "futures"
    contract_name = data.get("contract_spec", {}).get("name", ticker) if is_futures else ticker

    if is_futures:
        prompts = {
            "flash": f"""You are Flash 📈, CooperCorp Technical Analyst — FUTURES MODE.
Analyze {contract_name} ({ticker}) for entry. Market data:
{data_summary}{mtf_block}
This is a FUTURES CONTRACT. Consider: margin=${data.get('contract_spec',{}).get('margin','?')}, tick value=${data.get('contract_spec',{}).get('tick_value','?')}.
Provide: price, entry zone, stop (in ticks), target (in ticks), R:R ratio, RSI, trend direction, volume.
Futures trade nearly 24h — note session context (Globex vs RTH).
End with: TECHNICAL SCORE: X/10""",

            "macro": f"""You are Macro 🌍, CooperCorp Fundamentals Analyst — FUTURES MODE.
Analyze {contract_name} ({ticker}). Market data:
{data_summary}{intel_block}
This is a {data.get('contract_spec',{}).get('asset_class','').upper()} futures contract.
For FX futures: analyze central bank policy, rate differentials, economic data.
For commodity futures: analyze supply/demand, seasonal patterns, geopolitical risk.
For index futures: analyze equity fundamentals, VIX, sector rotation.
For crypto futures: analyze on-chain metrics, regulatory news, institutional flows.
Consider FOMC proximity impact on this asset class.
End with: FUNDAMENTAL SCORE: X/10""",

            "pulse": f"""You are Pulse 💬, CooperCorp Sentiment Analyst — FUTURES MODE.
Analyze {contract_name} ({ticker}) sentiment. Market data:
{data_summary}{intel_block}
This is a futures contract — consider: COT (Commitment of Traders) positioning if known,
institutional vs retail sentiment, open interest trends, funding rates (crypto).
Check for geopolitical risk events affecting this asset class.
End with: SENTIMENT SCORE: X/10""",
        }
    else:
        prompts = {
            "flash": f"""You are Flash 📈, CooperCorp Technical Analyst.
Analyze {ticker} for intraday entry. Market data:
{data_summary}{mtf_block}
Provide: price, entry zone, stop (-2%), target (+6%), R:R ratio, RSI status, SMA trend, volume vs average.
If MTF confluence data is available, factor it in — multiple timeframes aligning is a stronger signal.
End with: TECHNICAL SCORE: X/10""",

            "macro": f"""You are Macro 🌍, CooperCorp Fundamentals Analyst.
Analyze {ticker} fundamentals. Market data:
{data_summary}{intel_block}
Provide: main catalyst, days to earnings, sector trend, relative P/E, insider activity, key macro risks.
Consider: dark pool activity, whale moves, ETF sector flows, FOMC proximity if data available.
If earnings whisper data shows high bar, flag the risk of earnings miss.
End with: FUNDAMENTAL SCORE: X/10""",

            "pulse": f"""You are Pulse 💬, CooperCorp Sentiment & Options Analyst.
Analyze {ticker} sentiment. Market data:
{data_summary}{intel_block}
Reddit sentiment: {json.dumps(data.get('reddit_sentiment', {}))[:300]}
Provide: news tone, options PCR, unusual options activity, Reddit/social buzz, dark pool signals, fear/greed.
End with: SENTIMENT SCORE: X/10""",
        }

    reports = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(run_agent, k, v): k for k, v in prompts.items()}
        for f in as_completed(futures):
            name = futures[f]
            try:
                reports[name] = f.result(timeout=100)
            except Exception as e:
                reports[name] = f"[{name} timeout: {e}]"

    return reports


def research_manager_synthesis(ticker: str, reports: dict, data: dict) -> str:
    """Step 3 (Gap 3): Research Manager synthesizes analyst reports + BM25 memory."""
    from tradingagents.agents.managers.research_synthesizer import synthesize_research
    return synthesize_research(
        ticker=ticker,
        flash_report=reports.get("flash", ""),
        macro_report=reports.get("macro", ""),
        pulse_report=reports.get("pulse", ""),
        score=float(data.get("score", 5.0)),
        price=float(data.get("price", 0.0)),
    )


def run_debate(ticker: str, briefing: str, max_rounds: int = 2) -> tuple:
    """Step 4 (Gap 4): Bull/Bear debate with configurable rounds."""
    from tradingagents.graph.debate_engine import run_debate as _run_debate, format_debate_summary

    bull_prompt = f"""You are Bull 🐂. The Research Manager has prepared this briefing for {ticker}:
{briefing[:1500]}
Make the strongest 3-bullet bullish case. What will drive the stock up?
End with: BULL CONVICTION: X/10"""

    bear_prompt = f"""You are Bear 🐻. The Research Manager has prepared this briefing for {ticker}:
{briefing[:1500]}
Make the strongest 3-bullet bearish/risk case. What could go wrong?
End with: BEAR RISK: X/10"""

    # Round 1: initial positions
    with ThreadPoolExecutor(max_workers=2) as ex:
        bull_f = ex.submit(run_agent, "bull", bull_prompt, 90)
        bear_f = ex.submit(run_agent, "bear", bear_prompt, 90)
        bull_r1 = bull_f.result(timeout=100)
        bear_r1 = bear_f.result(timeout=100)

    # Additional rounds via debate_engine
    bull_final, bear_final, conviction_delta = _run_debate(
        ticker, briefing, bull_r1, bear_r1, max_rounds=max_rounds
    )

    summary = format_debate_summary(ticker, bull_final, bear_final, conviction_delta, max_rounds)
    return bull_final, bear_final, conviction_delta, summary


def process_signal(ticker: str, reports: dict, debate_summary: str,
                   raw_score: float, conviction_delta: float) -> dict:
    """Step 5 (Gap 5): Extract structured signal from all agent outputs."""
    from tradingagents.graph.signal_processor import extract_signal, format_signal_card

    all_text = "\n".join(reports.values()) + "\n" + debate_summary
    signal = extract_signal(
        ticker=ticker,
        flash_report=reports.get("flash", ""),
        macro_report=reports.get("macro", ""),
        pulse_report=reports.get("pulse", ""),
        debate_summary=debate_summary,
        raw_score=raw_score,
        conviction_delta=conviction_delta,
    )
    signal["card"] = format_signal_card(signal)
    return signal


def post_discord(channel_id: str, msg: str):
    subprocess.run(
        ["openclaw", "message", "send", "--channel", "discord",
         "--target", channel_id, "--message", msg],
        timeout=15, check=False
    )


def main():
    parser = argparse.ArgumentParser(description="Full pipeline scan with all 5 upstream gaps closed")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--rounds", type=int, default=2, help="Debate rounds (default: 2)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--threshold", type=float, default=7.0)
    parser.add_argument("--conviction-min", type=int, default=7)
    args = parser.parse_args()

    ticker = args.ticker.upper()
    print(f"\n{'='*60}")
    print(f"🦅 CooperCorp Full Pipeline — {ticker}")
    print(f"Debate rounds: {args.rounds} | Threshold: {args.threshold}")
    print(f"{'='*60}\n")

    # ── Pre-flight: Drawdown halt check (before spending any LLM tokens) ────
    try:
        dd_path = REPO / "logs" / "drawdown_state.json"
        if dd_path.exists():
            dd = json.loads(dd_path.read_text())
            if dd.get("halted"):
                print(f"🛑 DRAWDOWN HALT ACTIVE — portfolio down {dd.get('drawdown_pct','?')}%")
                print("   No new analysis until drawdown circuit breaker resets.")
                return {"ticker": ticker, "action": "skip", "reason": "drawdown_halt"}
    except Exception as e:
        print(f"WARN: drawdown check failed (non-fatal): {e}")

    # Step 1: Market data
    print("📊 Step 1: Gathering market data...")
    data = gather_market_data(ticker)
    raw_score = float(data.get("score", 5.0))
    print(f"   Pre-score: {raw_score:.1f} | Price: ${data.get('price', 0):.2f}")

    if raw_score < 5.0:
        print(f"   Pre-score {raw_score:.1f} too low — skipping pipeline")
        return {"ticker": ticker, "action": "skip", "reason": "pre_score_too_low"}

    # Step 2: Analyst team
    print("\n👥 Step 2: Running analyst team (Flash + Macro + Pulse in parallel)...")
    reports = run_analyst_team(ticker, data)
    for name, r in reports.items():
        score_line = next((l for l in r.splitlines() if "SCORE" in l.upper()), "")
        print(f"   {name.upper()}: {score_line[:60] or r[:60]}")

    # Step 3: Research Manager
    print("\n📋 Step 3: Research Manager synthesis + BM25 memory injection...")
    briefing = research_manager_synthesis(ticker, reports, data)
    print(f"   Briefing: {len(briefing)} chars | Memory: {'included' if 'Relevant past' in briefing else 'no similar situations yet'}")

    # Step 4: Bull/Bear debate
    print(f"\n⚔️  Step 4: Bull/Bear debate ({args.rounds} rounds)...")
    bull_final, bear_final, conviction_delta, debate_summary = run_debate(
        ticker, briefing, max_rounds=args.rounds
    )
    print(f"   Conviction delta: {conviction_delta:+.1f} ({'bull' if conviction_delta > 0 else 'bear'} wins)")

    # Step 5: Signal processing
    print("\n🔬 Step 5: Signal processing...")
    signal = process_signal(ticker, reports, debate_summary, raw_score, conviction_delta)
    final_score = signal["score"]
    direction = signal["direction"]
    confidence = signal["confidence"]
    print(f"   Direction: {direction} | Score: {final_score:.1f} | Confidence: {confidence}/10")

    # Intelligence bonus injection (guru signals + sentiment + short interest + drawdown + kelly)
    intel = load_intelligence_context(REPO, ticker)

    # Second drawdown check (after loading intel — catches mid-session halts)
    if intel.get("halted"):
        print(f"🛑 DRAWDOWN HALT: {intel.get('halt_reason', 'active')}")
        return {"ticker": ticker, "action": "skip", "reason": "drawdown_halt"}

    if intel["score_bonus"] != 0:
        final_score = min(10.0, final_score + intel["score_bonus"])
        signal["score"] = final_score
        print(f"Intelligence bonus: {intel['score_bonus']:+.1f} → adjusted score: {final_score:.1f}")
        for reason in intel["reasons"]:
            print(f"  {reason}")
    print(f"   {signal['card']}")

    # Decision
    threshold = args.threshold
    meets_threshold = final_score >= threshold and confidence >= args.conviction_min

    print(f"\n{'✅' if meets_threshold else '❌'} Decision: {direction} | Score {final_score:.1f} vs threshold {threshold}")

    # Post summary to war-room
    from datetime import datetime
    import pytz
    ET = pytz.timezone("America/New_York")
    now = datetime.now(ET).strftime("%I:%M %p ET")

    summary_msg = f"""🦅 **Full Pipeline Analysis — {ticker}** | {now}
📊 Score: {final_score:.1f}/10 | Direction: {direction} | Confidence: {confidence}/10
⚔️ Debate ({args.rounds} rounds): {'🐂 Bull +' if conviction_delta > 0 else '🐻 Bear +'}{abs(conviction_delta):.1f}
{signal['card']}
{'✅ **THRESHOLD MET** — Passing to trade gate' if meets_threshold else '⏭️ Below threshold — no trade'}
— Cooper 🦅 | Full Pipeline"""

    post_discord("1469763123010342953", summary_msg)

    # Execute if threshold met
    if meets_threshold and not args.dry_run and direction in ("BUY",):
        print("\n🔴 Executing trade via trade_gate.py...")
        gate_result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "trade_gate.py"),
             "--ticker", ticker,
             "--action", "BUY",
             "--score", str(round(final_score, 2)),
             "--conviction", str(confidence),
             "--source", "full_pipeline",
             "--note", f"debate_delta={conviction_delta:+.1f}"],
            capture_output=True, text=True, timeout=120, cwd=str(REPO)
        )
        print(gate_result.stdout[-500:])
        if gate_result.stderr:
            print("ERR:", gate_result.stderr[-200:])

    result = {
        "ticker": ticker,
        "pre_score": raw_score,
        "final_score": final_score,
        "direction": direction,
        "confidence": confidence,
        "conviction_delta": conviction_delta,
        "debate_rounds": args.rounds,
        "threshold_met": meets_threshold,
        "action": "trade" if meets_threshold and not args.dry_run else "skip",
    }
    print(f"\n{json.dumps(result, indent=2)}")
    return result


if __name__ == "__main__":
    main()
