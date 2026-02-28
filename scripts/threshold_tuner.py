#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Auto-Threshold Tuner
Reads win-rate data from SQLite DB and auto-adjusts entry score thresholds.
Run: python3 scripts/threshold_tuner.py
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

STRATEGY_CONFIG = REPO_ROOT / "config" / "strategy.json"
DISCORD_CHANNEL = "1468621074999541810"
MIN_THRESHOLD = 6.0
MAX_THRESHOLD = 8.5
MIN_SIGNALS_FOR_TUNING = 20
DECAY_WR = 0.55
EXCESS_WR = 0.75


def load_config() -> dict:
    try:
        with open(STRATEGY_CONFIG) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict):
    with open(STRATEGY_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


def post_report(message: str):
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", DISCORD_CHANNEL, "--message", message],
            timeout=30, capture_output=True
        )
    except Exception as e:
        print(f"Discord post failed: {e}")


def run_tuner():
    from tradingagents.learning.win_rate_tracker import get_global_stats, detect_strategy_decay
    from tradingagents.db.signal_db import get_all_stats

    global_stats = get_global_stats()
    total = global_stats.get("total_trades", 0)
    wr = global_stats.get("win_rate")
    avg_pnl = global_stats.get("avg_pnl", 0)

    cfg = load_config()
    current_threshold = cfg.get("entry_thresholds", {}).get("morning", 7.0)
    new_threshold = current_threshold
    action_taken = "No change"

    if total >= MIN_SIGNALS_FOR_TUNING and wr is not None:
        if wr < DECAY_WR:
            new_threshold = min(current_threshold + 0.2, MAX_THRESHOLD)
            action_taken = f"Raised {current_threshold:.1f} → {new_threshold:.1f} (WR={wr:.1%} < {DECAY_WR:.0%})"
        elif wr > EXCESS_WR:
            new_threshold = max(current_threshold - 0.2, MIN_THRESHOLD)
            action_taken = f"Lowered {current_threshold:.1f} → {new_threshold:.1f} (WR={wr:.1%} > {EXCESS_WR:.0%})"

        if new_threshold != current_threshold:
            if "entry_thresholds" not in cfg:
                cfg["entry_thresholds"] = {}
            cfg["entry_thresholds"]["morning"] = new_threshold
            cfg["entry_thresholds"]["afternoon"] = round(new_threshold + 0.5, 1)
            save_config(cfg)

    # Build ticker breakdown
    all_stats = get_all_stats()
    best = [s for s in all_stats if s.get("win_rate", 0) >= 0.6 and s.get("total_signals", 0) >= 3]
    worst = [s for s in all_stats if s.get("win_rate", 0) < 0.4 and s.get("total_signals", 0) >= 3]

    decay_flag, decay_msg = detect_strategy_decay()

    report = (
        f"📊 **THRESHOLD TUNER REPORT** | {datetime.now().strftime('%Y-%m-%d %H:%M ET')}\n"
        f"Total Trades: {total} | Win Rate: {wr:.1%} | Avg P&L: {avg_pnl:+.2f}%\n"
        f"Threshold: {current_threshold:.1f} → {action_taken}\n"
    )
    if decay_flag:
        report += f"⚠️ {decay_msg}\n"
    if best:
        report += f"🟢 Top tickers: {', '.join(s['ticker'] for s in best[:5])}\n"
    if worst:
        report += f"🔴 Struggling: {', '.join(s['ticker'] for s in worst[:5])}\n"
    report += "— Cooper 🦅 | Auto-Tuner"

    print(report)
    if total >= 5:
        post_report(report)
    return report


if __name__ == "__main__":
    run_tuner()
