#!/usr/bin/env python3
"""
CooperCorp PRJ-002 — Post equity curve chart to Discord.
Reads logs/equity_curve.jsonl, generates PNG chart, posts to #cooper-study.
Run: python3 scripts/post_equity_chart.py
"""
import sys
import os
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

EQUITY_CURVE_FILE = REPO_ROOT / "logs" / "equity_curve.jsonl"
COOPER_STUDY_CHANNEL = "1468621074999541810"
INITIAL_CAPITAL = 100_499.0
TARGET = 1_000_000.0


def load_equity_curve() -> list:
    if not EQUITY_CURVE_FILE.exists():
        return []
    entries = []
    with open(EQUITY_CURVE_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    return entries


def generate_chart(entries: list, output_path: str) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        dates = []
        values = []
        for e in entries:
            try:
                d = datetime.fromisoformat(e.get("date", e.get("timestamp", "")))
                v = float(e.get("equity", e.get("portfolio_value", 0)))
                if v > 0:
                    dates.append(d)
                    values.append(v)
            except Exception:
                pass

        if len(values) < 2:
            # Generate sample data for demo
            from datetime import timedelta
            now = datetime.now()
            dates = [now - timedelta(days=i) for i in range(7, -1, -1)]
            values = [INITIAL_CAPITAL] * 8

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [3, 1]})
        fig.patch.set_facecolor("#0d1117")

        # Equity curve
        color = "#00ff88" if values[-1] >= values[0] else "#ff4444"
        ax1.fill_between(dates, values, alpha=0.2, color=color)
        ax1.plot(dates, values, color=color, linewidth=2.5, label="Portfolio Value")
        ax1.axhline(y=INITIAL_CAPITAL, color="#888", linestyle="--", linewidth=1, alpha=0.7, label=f"Start ${INITIAL_CAPITAL:,.0f}")
        ax1.axhline(y=TARGET, color="#ffd700", linestyle="--", linewidth=1, alpha=0.5, label=f"Target $1M")

        # Milestones
        milestones = [
            (INITIAL_CAPITAL * 1.25, "25%", "#4CAF50"),
            (INITIAL_CAPITAL * 1.50, "50%", "#2196F3"),
            (INITIAL_CAPITAL * 1.75, "75%", "#FF9800"),
        ]
        for val, label, c in milestones:
            if val < max(values) * 1.2:
                ax1.axhline(y=val, color=c, linestyle=":", linewidth=0.8, alpha=0.4)

        ax1.set_facecolor("#161b22")
        ax1.tick_params(colors="#ccc")
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax1.legend(facecolor="#0d1117", labelcolor="#ccc", framealpha=0.8)
        ax1.set_title("CooperCorp PRJ-002 — Equity Curve", color="#fff", fontsize=14, pad=10)
        ax1.grid(True, color="#333", linestyle="--", alpha=0.4)
        for spine in ax1.spines.values():
            spine.set_edgecolor("#333")

        # P&L % bar chart
        pnl_pcts = [(v - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100 for v in values]
        bar_colors = ["#00ff88" if p >= 0 else "#ff4444" for p in pnl_pcts]
        ax2.bar(dates, pnl_pcts, color=bar_colors, alpha=0.7, width=0.8)
        ax2.axhline(y=0, color="#888", linewidth=0.8)
        ax2.set_facecolor("#161b22")
        ax2.tick_params(colors="#ccc")
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:+.1f}%"))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax2.set_title("Daily P&L %", color="#aaa", fontsize=10)
        ax2.grid(True, color="#333", linestyle="--", alpha=0.4)
        for spine in ax2.spines.values():
            spine.set_edgecolor("#333")

        # Stats box
        current = values[-1]
        total_return = (current - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        progress = (current - INITIAL_CAPITAL) / (TARGET - INITIAL_CAPITAL) * 100
        stats_text = (
            f"Portfolio: ${current:,.2f}  |  "
            f"Return: {total_return:+.2f}%  |  "
            f"Progress to $1M: {progress:.1f}%  |  "
            f"Days tracked: {len(values)}"
        )
        fig.text(0.5, 0.01, stats_text, ha="center", color="#aaa", fontsize=9,
                 bbox=dict(boxstyle="round", facecolor="#161b22", edgecolor="#333"))

        plt.tight_layout(rect=[0, 0.04, 1, 1])
        plt.savefig(output_path, dpi=150, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close()
        return True
    except ImportError:
        print("matplotlib not installed — install with: pip install matplotlib")
        return False
    except Exception as e:
        print(f"Chart generation error: {e}")
        return False


def generate_options_payoff_chart(symbol: str, strike: float, premium: float,
                                   option_type: str = "call", output_path: str = None) -> bool:
    """Generate options P&L payoff diagram at expiry."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        prices = np.linspace(strike * 0.7, strike * 1.3, 200)

        if option_type.lower() == "call":
            pnl = np.maximum(prices - strike, 0) - premium
            title = f"{symbol} Long Call — Strike ${strike:.2f} | Premium ${premium:.2f}"
        else:
            pnl = np.maximum(strike - prices, 0) - premium
            title = f"{symbol} Long Put — Strike ${strike:.2f} | Premium ${premium:.2f}"

        pnl_pct = pnl / premium * 100

        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor("#0d1117")
        ax.set_facecolor("#161b22")

        pos_mask = pnl >= 0
        neg_mask = pnl < 0
        ax.fill_between(prices, pnl_pct, 0, where=pos_mask, alpha=0.3, color="#00ff88")
        ax.fill_between(prices, pnl_pct, 0, where=neg_mask, alpha=0.3, color="#ff4444")
        ax.plot(prices, pnl_pct, color="#ffffff", linewidth=2)
        ax.axhline(y=0, color="#888", linewidth=1)
        ax.axvline(x=strike, color="#ffd700", linewidth=1, linestyle="--", alpha=0.7, label=f"Strike ${strike:.2f}")

        # Breakeven
        be = strike + premium if option_type.lower() == "call" else strike - premium
        ax.axvline(x=be, color="#00bcd4", linewidth=1, linestyle="--", alpha=0.7, label=f"Breakeven ${be:.2f}")

        ax.set_xlabel("Stock Price at Expiry", color="#ccc")
        ax.set_ylabel("P&L %", color="#ccc")
        ax.set_title(title, color="#fff", fontsize=12)
        ax.tick_params(colors="#ccc")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:+.0f}%"))
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:.0f}"))
        ax.legend(facecolor="#0d1117", labelcolor="#ccc")
        ax.grid(True, color="#333", linestyle="--", alpha=0.4)
        for spine in ax.spines.values():
            spine.set_edgecolor("#333")

        max_gain = max(pnl_pct)
        ax.text(0.98, 0.95, f"Max gain: +{max_gain:.0f}%\nMax loss: -100%",
                transform=ax.transAxes, ha="right", va="top",
                color="#aaa", fontsize=9,
                bbox=dict(boxstyle="round", facecolor="#0d1117", edgecolor="#333"))

        plt.tight_layout()
        plt.savefig(output_path or f"/tmp/{symbol}_payoff.png", dpi=120, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close()
        return True
    except Exception as e:
        print(f"Options payoff chart error: {e}")
        return False


def post_chart_to_discord(image_path: str, channel_id: str, caption: str):
    """Post chart PNG to Discord via openclaw CLI."""
    try:
        result = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target", channel_id,
             "--message", caption,
             "--media", image_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"Posted chart to Discord channel {channel_id}")
        else:
            print(f"Discord post error: {result.stderr}")
    except Exception as e:
        print(f"Failed to post chart: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default=COOPER_STUDY_CHANNEL, help="Discord channel ID")
    parser.add_argument("--options-payoff", action="store_true", help="Generate options payoff chart instead")
    parser.add_argument("--symbol", default="NVDA", help="Symbol for options chart")
    parser.add_argument("--strike", type=float, default=0, help="Options strike price")
    parser.add_argument("--premium", type=float, default=0, help="Options premium paid")
    parser.add_argument("--type", default="call", choices=["call", "put"], help="Option type")
    args = parser.parse_args()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        output_path = f.name

    if args.options_payoff and args.strike > 0:
        ok = generate_options_payoff_chart(
            args.symbol, args.strike, args.premium or 1.0,
            args.type, output_path
        )
        if ok:
            caption = f"📊 {args.symbol} {args.type.upper()} Payoff Diagram | Strike ${args.strike:.2f} | CooperCorp PRJ-002"
            post_chart_to_discord(output_path, args.channel, caption)
    else:
        entries = load_equity_curve()
        ok = generate_chart(entries, output_path)
        if ok:
            current = entries[-1].get("equity", INITIAL_CAPITAL) if entries else INITIAL_CAPITAL
            total_return = (current - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
            progress = (current - INITIAL_CAPITAL) / (TARGET - INITIAL_CAPITAL) * 100
            week = datetime.now().strftime("Week of %b %d, %Y")
            caption = (
                f"📈 **CooperCorp Equity Curve — {week}**\n"
                f"Portfolio: ${current:,.2f} | Return: {total_return:+.2f}% | "
                f"Progress to $1M: {progress:.1f}%\n"
                f"— Cooper 🦅 | PRJ-002"
            )
            post_chart_to_discord(output_path, args.channel, caption)
        else:
            print("Chart generation failed — matplotlib may not be installed")

    try:
        os.unlink(output_path)
    except Exception:
        pass


if __name__ == "__main__":
    main()
