"""
CooperCorp PRJ-002 — Walk-Forward Backtesting Engine
Simulates trading strategy on historical data using RSI + volume + SMA scoring.
"""
import json
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI from list of close prices."""
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [abs(d) for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _simulate_score(closes: list, volumes: list, idx: int) -> float:
    """Generate a simplified scan score for backtesting (0-10)."""
    if idx < 20:
        return 0.0
    window_closes = closes[max(0, idx-20):idx+1]
    window_vols = volumes[max(0, idx-5):idx+1]
    rsi = _calculate_rsi(window_closes)
    sma20 = sum(window_closes[-20:]) / min(20, len(window_closes))
    sma5 = sum(window_closes[-5:]) / min(5, len(window_closes))
    current = closes[idx]
    avg_vol = sum(volumes[max(0, idx-20):idx]) / 20 if idx >= 20 else 1
    vol_ratio = volumes[idx] / avg_vol if avg_vol > 0 else 1.0

    score = 5.0  # base
    # RSI momentum
    if 55 <= rsi <= 70:
        score += 1.0
    elif rsi > 70:
        score += 0.5  # overbought
    elif rsi < 40:
        score -= 1.0
    # SMA trend
    if current > sma20:
        score += 0.8
    if sma5 > sma20:
        score += 0.5
    # Volume confirmation
    if vol_ratio > 1.5:
        score += 0.7
    elif vol_ratio > 1.2:
        score += 0.3
    # Price momentum (3-day)
    if idx >= 3 and closes[idx] > closes[idx-3]:
        score += 0.5
    return max(0.0, min(10.0, score))


class BacktestEngine:
    def __init__(self, initial_capital: float = 100_000.0):
        self.initial_capital = initial_capital

    def run_backtest(
        self,
        tickers: list,
        score_threshold: float = 7.0,
        lookback_days: int = 90,
        stop_loss: float = 0.03,
        take_profit: float = 0.08,
    ) -> dict:
        """
        Run backtest across tickers over lookback period.
        Returns comprehensive performance metrics.
        """
        try:
            import yfinance as yf
        except ImportError:
            return {"error": "yfinance not installed"}

        all_trades = []
        capital = self.initial_capital
        equity_curve = [{"date": datetime.now().isoformat(), "equity": capital}]

        for ticker in tickers:
            try:
                # Fetch data
                period = f"{lookback_days + 30}d"
                hist = yf.Ticker(ticker).history(period=period, interval="1d")
                if hist.empty or len(hist) < 25:
                    continue

                closes = hist["Close"].tolist()
                opens = hist["Open"].tolist()
                volumes = hist["Volume"].tolist()
                dates = hist.index.tolist()

                position = None
                for i in range(20, len(closes) - 1):
                    if position is None:
                        # Check entry
                        score = _simulate_score(closes, volumes, i)
                        if score >= score_threshold:
                            entry_price = opens[i+1]  # enter at next day open
                            position = {
                                "ticker": ticker,
                                "entry_date": str(dates[i+1])[:10],
                                "entry_price": entry_price,
                                "entry_idx": i+1,
                                "score": score,
                                "shares": int((capital * 0.05) / entry_price) if entry_price > 0 else 0
                            }
                    else:
                        # Check exit
                        current = closes[i]
                        pnl_pct = (current - position["entry_price"]) / position["entry_price"]
                        days_held = i - position["entry_idx"]

                        exit_reason = None
                        exit_price = current

                        if pnl_pct <= -stop_loss:
                            exit_reason = "stop_loss"
                        elif pnl_pct >= take_profit:
                            exit_reason = "take_profit"
                        elif days_held >= 10:
                            exit_reason = "max_hold"

                        if exit_reason:
                            pnl_dollar = position["shares"] * (exit_price - position["entry_price"])
                            capital += pnl_dollar
                            all_trades.append({
                                "ticker": ticker,
                                "entry_date": position["entry_date"],
                                "exit_date": str(dates[i])[:10],
                                "entry_price": round(position["entry_price"], 2),
                                "exit_price": round(exit_price, 2),
                                "pnl_pct": round(pnl_pct * 100, 2),
                                "pnl_dollar": round(pnl_dollar, 2),
                                "score": round(position["score"], 1),
                                "exit_reason": exit_reason,
                                "win": pnl_pct > 0
                            })
                            equity_curve.append({
                                "date": str(dates[i])[:10],
                                "equity": round(capital, 2)
                            })
                            position = None

            except Exception as e:
                print(f"[backtest] Error on {ticker}: {e}")
                continue

        # Compute stats
        if not all_trades:
            return {
                "total_return_pct": 0.0, "win_rate": 0.0, "total_trades": 0,
                "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
                "max_drawdown_pct": 0.0, "sharpe_ratio": 0.0,
                "trades": [], "equity_curve": equity_curve,
                "error": "No trades generated"
            }

        wins = [t for t in all_trades if t["win"]]
        losses = [t for t in all_trades if not t["win"]]
        win_rate = len(wins) / len(all_trades)
        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
        total_return = (capital - self.initial_capital) / self.initial_capital * 100

        # Max drawdown
        peak = self.initial_capital
        max_dd = 0.0
        running = self.initial_capital
        for t in all_trades:
            running += t["pnl_dollar"]
            if running > peak:
                peak = running
            dd = (peak - running) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Sharpe (simplified daily returns)
        daily_returns = [t["pnl_pct"] for t in all_trades]
        if len(daily_returns) > 1:
            mean_r = sum(daily_returns) / len(daily_returns)
            std_r = math.sqrt(sum((r - mean_r)**2 for r in daily_returns) / len(daily_returns))
            sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0
        else:
            sharpe = 0.0

        return {
            "total_return_pct": round(total_return, 2),
            "win_rate": round(win_rate, 3),
            "total_trades": len(all_trades),
            "wins": len(wins),
            "losses": len(losses),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "final_capital": round(capital, 2),
            "tickers": tickers,
            "params": {
                "score_threshold": score_threshold,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "lookback_days": lookback_days
            },
            "trades": all_trades,
            "equity_curve": equity_curve,
            "run_time": datetime.now().isoformat()
        }

    def save_results(self, result: dict, path=None):
        """Save backtest results to JSON."""
        out_path = Path(path) if path else REPO_ROOT / "logs" / "backtest_latest.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"[backtest] Results saved to {out_path}")
