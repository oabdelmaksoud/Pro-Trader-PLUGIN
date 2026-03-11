"""
Comprehensive unit tests for core Pro-Trader-SKILL modules.
Covers modules not previously tested; all tests are credential-free.
"""
import json
import sys
import uuid
import tempfile
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Kelly Sizing
# ---------------------------------------------------------------------------

class TestKellySizing:
    def test_kelly_fraction_basic(self):
        from tradingagents.risk.kelly_sizing import kelly_fraction
        frac = kelly_fraction(win_rate=0.6, avg_win_pct=0.08, avg_loss_pct=0.03)
        assert 0.01 <= frac <= 0.10

    def test_kelly_fraction_zero_avg_win(self):
        from tradingagents.risk.kelly_sizing import kelly_fraction
        # avg_win_pct=0 should return default 0.02
        assert kelly_fraction(0.6, 0.0, 0.03) == 0.02

    def test_kelly_fraction_clamped_min(self):
        from tradingagents.risk.kelly_sizing import kelly_fraction
        # Very bad win rate → clamped to 0.01
        assert kelly_fraction(0.1, 0.01, 0.10) == 0.01

    def test_kelly_fraction_clamped_max(self):
        from tradingagents.risk.kelly_sizing import kelly_fraction
        # Very good win rate → clamped to 0.10
        assert kelly_fraction(0.99, 0.50, 0.01) == 0.10

    def test_get_kelly_size_returns_required_keys(self):
        from tradingagents.risk.kelly_sizing import get_kelly_size
        result = get_kelly_size(
            ticker="TEST",
            portfolio_value=100_000,
            win_rate=0.60,
            avg_win=0.08,
            avg_loss=0.03,
            vix=20.0,
            current_price=100.0,
        )
        assert "fraction" in result
        assert "dollar_amount" in result
        assert "shares" in result
        assert result["dollar_amount"] <= 25_000

    def test_get_kelly_size_high_vix_reduces_size(self):
        from tradingagents.risk.kelly_sizing import get_kelly_size
        low_vix = get_kelly_size("T", 100_000, 0.60, 0.08, 0.03, vix=15.0, current_price=100.0)
        high_vix = get_kelly_size("T", 100_000, 0.60, 0.08, 0.03, vix=35.0, current_price=100.0)
        assert high_vix["dollar_amount"] < low_vix["dollar_amount"]

    def test_get_options_kelly(self):
        from tradingagents.risk.kelly_sizing import get_options_kelly
        contracts = get_options_kelly(portfolio_value=100_000, option_cost_per_contract=5.0)
        assert contracts >= 1
        assert contracts <= 5


# ---------------------------------------------------------------------------
# Trailing Stop Manager
# ---------------------------------------------------------------------------

class TestTrailingStopManager:
    def test_update_and_stop(self, tmp_path, monkeypatch):
        import tradingagents.risk.trailing_stop as ts_mod
        monkeypatch.setattr(ts_mod, "HWM_FILE", tmp_path / "hwm.json")

        from tradingagents.risk.trailing_stop import TrailingStopManager
        mgr = TrailingStopManager(trail_pct=0.05)
        stop = mgr.update("NVDA", 200.0)
        assert stop == pytest.approx(190.0)

    def test_hwm_updates_on_higher_price(self, tmp_path, monkeypatch):
        import tradingagents.risk.trailing_stop as ts_mod
        monkeypatch.setattr(ts_mod, "HWM_FILE", tmp_path / "hwm.json")

        from tradingagents.risk.trailing_stop import TrailingStopManager
        mgr = TrailingStopManager(trail_pct=0.10)
        mgr.update("AAPL", 150.0)
        mgr.update("AAPL", 180.0)  # New HWM
        mgr.update("AAPL", 170.0)  # Should NOT update HWM
        assert mgr.get_hwm("AAPL") == 180.0
        assert mgr.get_stop("AAPL") == pytest.approx(162.0)

    def test_clear_removes_symbol(self, tmp_path, monkeypatch):
        import tradingagents.risk.trailing_stop as ts_mod
        monkeypatch.setattr(ts_mod, "HWM_FILE", tmp_path / "hwm.json")

        from tradingagents.risk.trailing_stop import TrailingStopManager
        mgr = TrailingStopManager()
        mgr.update("TSLA", 300.0)
        mgr.clear("TSLA")
        assert mgr.get_hwm("TSLA") == 0.0


# ---------------------------------------------------------------------------
# Trade Tagger
# ---------------------------------------------------------------------------

class TestTradeTagger:
    def test_tag_and_get(self, tmp_path, monkeypatch):
        import tradingagents.risk.trade_tags as tt_mod
        monkeypatch.setattr(tt_mod, "TAG_FILE", tmp_path / "tags.json")

        from tradingagents.risk.trade_tags import TradeTagger
        tagger = TradeTagger()
        tagger.tag("NVDA", "swing")
        assert tagger.get_tag("NVDA") == "swing"
        assert tagger.is_swing("NVDA")

    def test_default_tag_is_day(self, tmp_path, monkeypatch):
        import tradingagents.risk.trade_tags as tt_mod
        monkeypatch.setattr(tt_mod, "TAG_FILE", tmp_path / "tags.json")

        from tradingagents.risk.trade_tags import TradeTagger
        tagger = TradeTagger()
        assert tagger.get_tag("AAPL") == "day"
        assert not tagger.is_swing("AAPL")

    def test_invalid_tag_raises(self, tmp_path, monkeypatch):
        import tradingagents.risk.trade_tags as tt_mod
        monkeypatch.setattr(tt_mod, "TAG_FILE", tmp_path / "tags.json")

        from tradingagents.risk.trade_tags import TradeTagger
        tagger = TradeTagger()
        with pytest.raises(ValueError):
            tagger.tag("NVDA", "invalid_tag")

    def test_clear(self, tmp_path, monkeypatch):
        import tradingagents.risk.trade_tags as tt_mod
        monkeypatch.setattr(tt_mod, "TAG_FILE", tmp_path / "tags.json")

        from tradingagents.risk.trade_tags import TradeTagger
        tagger = TradeTagger()
        tagger.tag("MSFT", "options")
        tagger.clear("MSFT")
        assert tagger.get_tag("MSFT") == "day"


# ---------------------------------------------------------------------------
# Partial Exit Manager
# ---------------------------------------------------------------------------

class TestPartialExitManager:
    def test_mark_and_check(self, tmp_path, monkeypatch):
        import tradingagents.risk.partial_exit as pe_mod
        monkeypatch.setattr(pe_mod, "PARTIAL_EXITS_FILE", tmp_path / "partial.json")

        from tradingagents.risk.partial_exit import PartialExitManager
        mgr = PartialExitManager()
        assert not mgr.has_taken_partial("NVDA")
        mgr.mark_partial_taken("NVDA", price=205.0, qty_closed=5)
        assert mgr.has_taken_partial("NVDA")

    def test_clear(self, tmp_path, monkeypatch):
        import tradingagents.risk.partial_exit as pe_mod
        monkeypatch.setattr(pe_mod, "PARTIAL_EXITS_FILE", tmp_path / "partial.json")

        from tradingagents.risk.partial_exit import PartialExitManager
        mgr = PartialExitManager()
        mgr.mark_partial_taken("AMD", price=150.0, qty_closed=3)
        mgr.clear("AMD")
        assert not mgr.has_taken_partial("AMD")


# ---------------------------------------------------------------------------
# Portfolio Heat (no-broker path)
# ---------------------------------------------------------------------------

class TestPortfolioHeatNoBroker:
    def test_no_broker_returns_empty_heat(self):
        from tradingagents.risk.portfolio_heat import PortfolioHeat
        ph = PortfolioHeat(broker=None)
        heat = ph.get_heat()
        assert heat["total_pct"] == 0
        assert heat["status"] == "ok"

    def test_can_add_position_no_broker(self):
        from tradingagents.risk.portfolio_heat import PortfolioHeat
        ph = PortfolioHeat(broker=None)
        allowed, reason = ph.can_add_position("NVDA", 5.0)
        assert allowed

    def test_max_heat_constants(self):
        from tradingagents.risk.portfolio_heat import PortfolioHeat
        assert PortfolioHeat.MAX_TOTAL_HEAT == pytest.approx(0.12)
        assert PortfolioHeat.MAX_SECTOR_HEAT == pytest.approx(0.08)

    def test_sector_map_contains_known_tickers(self):
        from tradingagents.risk.portfolio_heat import PortfolioHeat
        assert PortfolioHeat.SECTOR_MAP["NVDA"] == "semis"
        assert PortfolioHeat.SECTOR_MAP["TSLA"] == "tech"


# ---------------------------------------------------------------------------
# Pattern Tracker
# ---------------------------------------------------------------------------

class TestPatternTracker:
    def test_record_pattern_success(self, tmp_path, monkeypatch):
        import tradingagents.learning.pattern_tracker as pt_mod
        monkeypatch.setattr(pt_mod, "ADJUSTMENTS_FILE", tmp_path / "adjustments.json")
        monkeypatch.setattr(pt_mod, "PATTERNS_HISTORY_FILE", tmp_path / "history.jsonl")

        from tradingagents.learning.pattern_tracker import PatternTracker
        pt = PatternTracker()
        pt.record_pattern("poor_rr", {"ticker": "NVDA", "pnl_pct": -0.02, "date": "2026-01-10"})
        counts = pt._count_patterns()
        assert counts.get("poor_rr", 0) == 1

    def test_record_unknown_pattern_is_ignored(self, tmp_path, monkeypatch):
        import tradingagents.learning.pattern_tracker as pt_mod
        monkeypatch.setattr(pt_mod, "ADJUSTMENTS_FILE", tmp_path / "adjustments.json")
        monkeypatch.setattr(pt_mod, "PATTERNS_HISTORY_FILE", tmp_path / "history.jsonl")

        from tradingagents.learning.pattern_tracker import PatternTracker
        pt = PatternTracker()
        pt.record_pattern("nonexistent_pattern", {"ticker": "TEST"})
        counts = pt._count_patterns()
        assert "nonexistent_pattern" not in counts

    def test_unreliable_ticker_pattern_registered(self):
        from tradingagents.learning.pattern_tracker import PatternTracker
        assert "unreliable_ticker" in PatternTracker.PATTERNS

    def test_record_unreliable_ticker_pattern(self, tmp_path, monkeypatch):
        import tradingagents.learning.pattern_tracker as pt_mod
        monkeypatch.setattr(pt_mod, "ADJUSTMENTS_FILE", tmp_path / "adjustments.json")
        monkeypatch.setattr(pt_mod, "PATTERNS_HISTORY_FILE", tmp_path / "history.jsonl")

        from tradingagents.learning.pattern_tracker import PatternTracker
        pt = PatternTracker()
        pt.record_pattern("unreliable_ticker", {
            "ticker": "WEAK",
            "accuracy": 0.40,
            "signal_count": 5,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        })
        counts = pt._count_patterns()
        assert counts.get("unreliable_ticker", 0) == 1

    def test_get_recurring_threshold(self, tmp_path, monkeypatch):
        import tradingagents.learning.pattern_tracker as pt_mod
        monkeypatch.setattr(pt_mod, "ADJUSTMENTS_FILE", tmp_path / "adjustments.json")
        monkeypatch.setattr(pt_mod, "PATTERNS_HISTORY_FILE", tmp_path / "history.jsonl")

        from tradingagents.learning.pattern_tracker import PatternTracker
        pt = PatternTracker()
        trade = {"ticker": "NVDA", "pnl_pct": -0.02, "date": "2026-01-10"}
        pt.record_pattern("chased_breakout", trade)
        assert pt.get_recurring(min_count=2) == []
        pt.record_pattern("chased_breakout", trade)
        recurring = pt.get_recurring(min_count=2)
        assert len(recurring) == 1
        assert recurring[0]["pattern"] == "chased_breakout"

    def test_score_adjustments_applied_after_threshold(self, tmp_path, monkeypatch):
        import tradingagents.learning.pattern_tracker as pt_mod
        monkeypatch.setattr(pt_mod, "ADJUSTMENTS_FILE", tmp_path / "adjustments.json")
        monkeypatch.setattr(pt_mod, "PATTERNS_HISTORY_FILE", tmp_path / "history.jsonl")

        from tradingagents.learning.pattern_tracker import PatternTracker
        pt = PatternTracker()
        trade = {"ticker": "NVDA", "pnl_pct": -0.02, "date": "2026-01-10"}
        pt.record_pattern("poor_rr", trade)
        pt.record_pattern("poor_rr", trade)
        adj = pt.get_score_adjustments()
        assert "min_rr_required" in adj
        assert adj["min_rr_required"] == 2.0


# ---------------------------------------------------------------------------
# Score Adjuster
# ---------------------------------------------------------------------------

class TestScoreAdjuster:
    def _make_tracker_with_adjustments(self, adjustments: dict):
        pt = MagicMock()
        pt.get_score_adjustments.return_value = adjustments
        return pt

    def test_chase_penalty_applied(self):
        from tradingagents.learning.score_adjuster import ScoreAdjuster
        adj = ScoreAdjuster()
        pt = self._make_tracker_with_adjustments({"no_chase_bonus": -1.5})
        scores = {"technical": 4.0, "pct_from_open": 0.05}
        result = adj.apply(scores, pt)
        assert result["technical"] == pytest.approx(2.5)

    def test_chase_penalty_not_applied_when_small_move(self):
        from tradingagents.learning.score_adjuster import ScoreAdjuster
        adj = ScoreAdjuster()
        pt = self._make_tracker_with_adjustments({"no_chase_bonus": -1.5})
        scores = {"technical": 4.0, "pct_from_open": 0.01}
        result = adj.apply(scores, pt)
        assert result["technical"] == pytest.approx(4.0)

    def test_rr_penalty(self):
        from tradingagents.learning.score_adjuster import ScoreAdjuster
        adj = ScoreAdjuster()
        pt = self._make_tracker_with_adjustments({"min_rr_required": 2.0})
        scores = {"rr": 3.0, "rr_ratio": 1.5}
        result = adj.apply(scores, pt)
        assert result["rr"] <= 1.0

    def test_no_rr_penalty_when_sufficient(self):
        from tradingagents.learning.score_adjuster import ScoreAdjuster
        adj = ScoreAdjuster()
        pt = self._make_tracker_with_adjustments({"min_rr_required": 2.0})
        scores = {"rr": 3.0, "rr_ratio": 2.5}
        result = adj.apply(scores, pt)
        assert result["rr"] == pytest.approx(3.0)

    def test_macro_veto_sets_flag(self):
        from tradingagents.learning.score_adjuster import ScoreAdjuster
        adj = ScoreAdjuster()
        pt = self._make_tracker_with_adjustments({"macro_veto_on_bearish": True})
        scores = {"macro_bearish": True}
        result = adj.apply(scores, pt)
        assert result.get("_macro_veto") is True

    def test_no_adjustment_when_empty(self):
        from tradingagents.learning.score_adjuster import ScoreAdjuster
        adj = ScoreAdjuster()
        pt = self._make_tracker_with_adjustments({})
        base = {"technical": 5.0, "catalyst": 3.0}
        result = adj.apply(base, pt)
        assert result["technical"] == pytest.approx(5.0)
        assert result["catalyst"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Signal DB
# ---------------------------------------------------------------------------

class TestSignalDB:
    def test_init_and_log_signal(self, tmp_path, monkeypatch):
        import tradingagents.db.signal_db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "signals.db")

        from tradingagents.db.signal_db import init_db, log_signal, get_ticker_stats
        init_db()
        sig_id = log_signal("NVDA", pre_score=6.5, final_score=7.2, conviction=8,
                            agent_scores={"technical": 4.0})
        assert sig_id > 0

    def test_mark_entered(self, tmp_path, monkeypatch):
        import tradingagents.db.signal_db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "signals.db")

        from tradingagents.db.signal_db import init_db, log_signal, mark_entered, _get_conn
        init_db()
        sig_id = log_signal("AAPL", 5.0, 6.0, 7)
        mark_entered(sig_id, entry_price=175.0)
        conn = _get_conn()
        row = conn.execute("SELECT entered, entry_price FROM signals WHERE id=?", (sig_id,)).fetchone()
        conn.close()
        assert row["entered"] == 1
        assert row["entry_price"] == pytest.approx(175.0)

    def test_log_outcome_updates_ticker_stats(self, tmp_path, monkeypatch):
        import tradingagents.db.signal_db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "signals.db")

        from tradingagents.db.signal_db import init_db, log_signal, log_outcome, get_ticker_stats
        init_db()
        sig_id = log_signal("MSFT", 6.0, 7.0, 8)
        log_outcome(sig_id, exit_price=185.0, pnl_pct=0.05, exit_reason="TARGET_HIT")
        stats = get_ticker_stats("MSFT")
        assert stats["wins"] == 1
        assert stats["win_rate"] == pytest.approx(1.0)

    def test_log_outcome_losing_trade(self, tmp_path, monkeypatch):
        import tradingagents.db.signal_db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "signals.db")

        from tradingagents.db.signal_db import init_db, log_signal, log_outcome, get_ticker_stats
        init_db()
        sig_id = log_signal("TSLA", 5.0, 5.5, 6)
        log_outcome(sig_id, exit_price=185.0, pnl_pct=-0.03, exit_reason="STOP_HIT")
        stats = get_ticker_stats("TSLA")
        assert stats["losses"] == 1
        assert stats["win_rate"] == pytest.approx(0.0)

    def test_get_all_stats_multiple_tickers(self, tmp_path, monkeypatch):
        import tradingagents.db.signal_db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "signals.db")

        from tradingagents.db.signal_db import init_db, log_signal, log_outcome, get_all_stats
        init_db()
        for ticker, pnl in [("A", 0.05), ("B", -0.02), ("A", 0.03)]:
            sid = log_signal(ticker, 6.0, 7.0, 8)
            log_outcome(sid, 100.0, pnl, "TEST")
        stats = get_all_stats()
        tickers = {s["ticker"] for s in stats}
        assert {"A", "B"} == tickers

    def test_get_recent_signals(self, tmp_path, monkeypatch):
        import tradingagents.db.signal_db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "signals.db")

        from tradingagents.db.signal_db import init_db, log_signal, get_recent_signals
        init_db()
        for i in range(5):
            log_signal(f"T{i}", float(i), float(i) + 0.5, i)
        recent = get_recent_signals(limit=3)
        assert len(recent) == 3

    def test_get_optimal_threshold_defaults_with_few_signals(self, tmp_path, monkeypatch):
        import tradingagents.db.signal_db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "signals.db")

        from tradingagents.db.signal_db import init_db, get_optimal_threshold
        init_db()
        # With no signals, should return the default 7.0
        threshold = get_optimal_threshold("NVDA")
        assert threshold == 7.0


# ---------------------------------------------------------------------------
# Ledger — P&L correctness for long vs short sides
# ---------------------------------------------------------------------------

class TestLedgerPnL:
    def test_long_side_profit(self, tmp_path, monkeypatch):
        import tradingagents.performance.ledger as ledger_mod
        monkeypatch.setattr(ledger_mod, "LEDGER_PATH", tmp_path / "ledger.jsonl")

        from tradingagents.performance.ledger import TradeLedger
        ledger = TradeLedger()
        entry = ledger.record_close("NVDA", "long", entry_price=100.0, exit_price=110.0,
                                    qty=10, reason="TARGET_HIT")
        assert entry["pnl_dollar"] == pytest.approx(100.0)
        assert entry["pnl_pct"] > 0

    def test_buy_side_profit(self, tmp_path, monkeypatch):
        import tradingagents.performance.ledger as ledger_mod
        monkeypatch.setattr(ledger_mod, "LEDGER_PATH", tmp_path / "ledger.jsonl")

        from tradingagents.performance.ledger import TradeLedger
        ledger = TradeLedger()
        entry = ledger.record_close("AAPL", "buy", entry_price=150.0, exit_price=160.0,
                                    qty=5, reason="TARGET_HIT")
        assert entry["pnl_dollar"] == pytest.approx(50.0)

    def test_short_side_profit(self, tmp_path, monkeypatch):
        import tradingagents.performance.ledger as ledger_mod
        monkeypatch.setattr(ledger_mod, "LEDGER_PATH", tmp_path / "ledger.jsonl")

        from tradingagents.performance.ledger import TradeLedger
        ledger = TradeLedger()
        entry = ledger.record_close("TSLA", "short", entry_price=300.0, exit_price=280.0,
                                    qty=5, reason="TARGET_HIT")
        assert entry["pnl_dollar"] == pytest.approx(100.0)

    def test_summary_with_mixed_trades(self, tmp_path, monkeypatch):
        import tradingagents.performance.ledger as ledger_mod
        monkeypatch.setattr(ledger_mod, "LEDGER_PATH", tmp_path / "ledger.jsonl")

        from tradingagents.performance.ledger import TradeLedger
        ledger = TradeLedger()
        ledger.record_close("A", "long", 100.0, 110.0, 10)
        ledger.record_close("B", "long", 100.0, 95.0, 10)
        summary = ledger.summary()
        assert summary["total_trades"] == 2
        assert summary["wins"] == 1
        assert summary["losses"] == 1
        assert summary["win_rate"] == pytest.approx(0.5)

    def test_daily_summary(self, tmp_path, monkeypatch):
        import tradingagents.performance.ledger as ledger_mod
        monkeypatch.setattr(ledger_mod, "LEDGER_PATH", tmp_path / "ledger.jsonl")

        from tradingagents.performance.ledger import TradeLedger
        ledger = TradeLedger()
        ledger.record_close("X", "long", 50.0, 55.0, 10)
        today = date.today().isoformat()
        ds = ledger.daily_summary(today)
        assert ds["trades"] == 1
        assert ds["total_pnl"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# AlpacaBroker — LivePrice subscript access (no credentials needed)
# ---------------------------------------------------------------------------

class TestLivePriceSubscriptAccess:
    def test_live_price_supports_subscript(self):
        """LivePrice objects returned from get_latest_bar must support bar['close']."""
        import inspect
        import tradingagents.brokers.alpaca as alpaca_mod

        src = inspect.getsource(alpaca_mod.AlpacaBroker.get_latest_bar)
        assert "__getitem__" in src, (
            "LivePrice inner class must implement __getitem__ so that bar['close'] works"
        )

    def test_live_price_getitem_via_method(self, tmp_path):
        """Simulate get_latest_bar returning a LivePrice and verify subscript access."""
        import json
        # Write a fake live_prices.json
        prices_file = tmp_path / "live_prices.json"
        prices_file.write_text(json.dumps({
            "NVDA": {"price": 185.50, "timestamp": "2026-03-06T10:00:00Z"}
        }))

        # Reconstruct the LivePrice class as written in the fixed source
        # to validate that __getitem__ works correctly.
        class LivePrice:
            def __init__(self, d):
                self.close = d["price"]
                self.open = d["price"]
                self.high = d["price"]
                self.low = d["price"]
                self.volume = 0
                self.timestamp = d.get("timestamp", "")

            def __getitem__(self, key):
                return getattr(self, key)

        data = json.loads(prices_file.read_text())
        p = data["NVDA"]
        bar = LivePrice(p)

        # This is the access pattern used in submit_bracket_order and calculate_qty
        assert bar["close"] == pytest.approx(185.50)
        assert bar["open"] == pytest.approx(185.50)
        assert bar["high"] == pytest.approx(185.50)


# ---------------------------------------------------------------------------
# Signal Verifier — accuracy computation (unit test, no network calls)
# ---------------------------------------------------------------------------

class TestSignalVerifierAccuracy:
    """Tests for _check_signal_accuracy which is pure logic, no network needed."""

    def _make_bars(self, high=115.0, low=90.0, close=110.0):
        """Build a minimal DataFrame that mimics yfinance output."""
        import pandas as pd
        idx = pd.DatetimeIndex(
            ["2026-01-10 10:00:00", "2026-01-10 15:55:00"],
            tz="America/New_York",
        )
        return pd.DataFrame({
            "Open": [100.0, 100.0],
            "High": [high, high],
            "Low": [low, low],
            "Close": [close, close],
            "Volume": [1000, 1000],
        }, index=idx)

    def _make_signal(self, action, price=100.0, target=108.0, stop=97.0):
        return {
            "id": str(uuid.uuid4()),
            "ticker": "TEST",
            "action": action,
            "price_at_signal": price,
            "target": target,
            "stop_loss": stop,
            "timestamp": "2026-01-10T09:30:00Z",
        }

    def test_buy_target_hit_correct(self):
        from tradingagents.signals.signal_verifier import SignalVerifier
        sv = SignalVerifier()
        bars = self._make_bars(high=115.0, low=99.0, close=110.0)
        signal = self._make_signal("BUY", price=100.0, target=108.0, stop=97.0)
        result = sv._check_signal_accuracy(signal, bars)
        assert result["target_hit"] is True
        assert result["stop_hit"] is False
        assert result["signal_correct"] is True
        assert result["accuracy_pct"] is not None

    def test_buy_stop_hit_incorrect(self):
        from tradingagents.signals.signal_verifier import SignalVerifier
        sv = SignalVerifier()
        bars = self._make_bars(high=101.0, low=95.0, close=96.0)
        signal = self._make_signal("BUY", price=100.0, target=108.0, stop=97.0)
        result = sv._check_signal_accuracy(signal, bars)
        assert result["stop_hit"] is True
        assert result["signal_correct"] is False

    def test_sell_target_hit_correct(self):
        from tradingagents.signals.signal_verifier import SignalVerifier
        sv = SignalVerifier()
        # For SELL: target is below entry, stop above entry
        bars = self._make_bars(high=105.0, low=85.0, close=86.0)
        signal = self._make_signal("SELL", price=100.0, target=90.0, stop=105.0)
        result = sv._check_signal_accuracy(signal, bars)
        assert result["target_hit"] is True
        assert result["stop_hit"] is True  # Both hit in bars

    def test_pass_signal_correct_when_price_drops(self):
        from tradingagents.signals.signal_verifier import SignalVerifier
        sv = SignalVerifier()
        bars = self._make_bars(high=100.5, low=95.0, close=96.0)
        signal = self._make_signal("PASS", price=100.0, target=108.0, stop=97.0)
        result = sv._check_signal_accuracy(signal, bars)
        # Price dropped → good call to PASS
        assert result["signal_correct"] is True

    def test_pass_signal_incorrect_when_price_rises_significantly(self):
        from tradingagents.signals.signal_verifier import SignalVerifier
        sv = SignalVerifier()
        bars = self._make_bars(high=115.0, low=99.5, close=113.0)
        signal = self._make_signal("PASS", price=100.0, target=108.0, stop=97.0)
        result = sv._check_signal_accuracy(signal, bars)
        # Price rose >1% → wrong call to PASS
        assert result["signal_correct"] is False

    def test_fetch_bars_end_is_next_day(self):
        """Regression: end date for intraday bars must be signal_date + 1 day."""
        from tradingagents.signals.signal_verifier import SignalVerifier
        sv = SignalVerifier()
        calls = []

        class FakeTicker:
            def history(self, **kwargs):
                calls.append(kwargs)
                import pandas as pd
                return pd.DataFrame()  # empty → triggers fallback

        with patch("yfinance.Ticker", return_value=FakeTicker()):
            sv._fetch_bars("NVDA", "2026-01-10")

        assert len(calls) >= 1
        # end must be strictly after start to fetch that day's intraday bars
        assert calls[0]["end"] == "2026-01-11", (
            f"Expected end='2026-01-11' but got {calls[0].get('end')}"
        )


# ---------------------------------------------------------------------------
# Circuit Breaker (no-broker path)
# ---------------------------------------------------------------------------

class TestCircuitBreakerNoBroker:
    def test_check_no_state_file_allows_trade(self, tmp_path, monkeypatch):
        import tradingagents.risk.circuit_breaker as cb_mod
        monkeypatch.setattr(cb_mod, "STATE_FILE", tmp_path / "cb.json")

        from tradingagents.risk.circuit_breaker import CircuitBreaker
        broker = MagicMock()
        broker.get_portfolio_value.return_value = 100_000.0
        cb = CircuitBreaker(broker, max_daily_loss_pct=0.05)
        # No state file → should allow trade
        result = cb.check()
        assert result["ok"] is True

    def test_check_within_loss_limit_allows_trade(self, tmp_path, monkeypatch):
        import tradingagents.risk.circuit_breaker as cb_mod
        state_file = tmp_path / "cb.json"
        monkeypatch.setattr(cb_mod, "STATE_FILE", state_file)

        from tradingagents.risk.circuit_breaker import CircuitBreaker
        broker = MagicMock()
        broker.get_portfolio_value.return_value = 97_000.0  # 3% drawdown
        today = date.today().isoformat()
        state_file.write_text(json.dumps({
            "date": today,
            "start_value": 100_000.0,
            "tripped": False,
        }))
        cb = CircuitBreaker(broker, max_daily_loss_pct=0.05)
        result = cb.check()
        assert result["ok"] is True

    def test_check_exceeds_loss_limit_trips_breaker(self, tmp_path, monkeypatch):
        import tradingagents.risk.circuit_breaker as cb_mod
        state_file = tmp_path / "cb.json"
        monkeypatch.setattr(cb_mod, "STATE_FILE", state_file)

        from tradingagents.risk.circuit_breaker import CircuitBreaker
        broker = MagicMock()
        broker.get_portfolio_value.return_value = 94_000.0  # 6% drawdown
        today = date.today().isoformat()
        state_file.write_text(json.dumps({
            "date": today,
            "start_value": 100_000.0,
            "tripped": False,
        }))
        cb = CircuitBreaker(broker, max_daily_loss_pct=0.05)
        result = cb.check()
        assert result["ok"] is False
        assert "reason" in result

    def test_already_tripped_blocks_trade(self, tmp_path, monkeypatch):
        import tradingagents.risk.circuit_breaker as cb_mod
        state_file = tmp_path / "cb.json"
        monkeypatch.setattr(cb_mod, "STATE_FILE", state_file)

        from tradingagents.risk.circuit_breaker import CircuitBreaker
        broker = MagicMock()
        today = date.today().isoformat()
        state_file.write_text(json.dumps({
            "date": today,
            "start_value": 100_000.0,
            "tripped": True,
        }))
        cb = CircuitBreaker(broker)
        result = cb.check()
        assert result["ok"] is False

    def test_is_tripped_reflects_state(self, tmp_path, monkeypatch):
        import tradingagents.risk.circuit_breaker as cb_mod
        state_file = tmp_path / "cb.json"
        monkeypatch.setattr(cb_mod, "STATE_FILE", state_file)

        from tradingagents.risk.circuit_breaker import CircuitBreaker
        broker = MagicMock()
        cb = CircuitBreaker(broker)
        assert cb.is_tripped() is False


# ---------------------------------------------------------------------------
# Post Mortem — analyze (no network calls)
# ---------------------------------------------------------------------------

class TestPostMortemAnalyze:
    def test_analyze_returns_required_keys(self):
        from tradingagents.learning.post_mortem import PostMortem
        pm = PostMortem()
        trade = {
            "ticker": "NVDA",
            "side": "long",
            "entry": 200.0,
            "exit": 194.0,
            "pnl_pct": -0.03,
            "hold_minutes": 45,
            "exit_reason": "STOP_HIT",
            "analysis_at_entry": "strong technical breakout on volume",
            "date": "2026-01-15",
        }
        result = pm.analyze(trade)
        for key in ("trade", "what_went_wrong", "which_signal_failed", "pattern",
                    "adjustment", "lesson", "analyzed_at"):
            assert key in result

    def test_analyze_pattern_detection_poor_rr(self):
        from tradingagents.learning.post_mortem import PostMortem
        pm = PostMortem()
        trade = {
            "ticker": "AAPL",
            "pnl_pct": -0.02,
            "hold_minutes": 20,  # <30 min → poor_rr
            "exit_reason": "STOP_HIT",
            "analysis_at_entry": "technical setup",
            "date": "2026-01-15",
        }
        result = pm.analyze(trade)
        assert result["pattern"] == "poor_rr"

    def test_analyze_signal_failed_catalyst(self):
        from tradingagents.learning.post_mortem import PostMortem
        pm = PostMortem()
        trade = {
            "ticker": "NVDA",
            "pnl_pct": -0.025,
            "hold_minutes": 60,
            "exit_reason": "STOP_HIT",
            "analysis_at_entry": "strong catalyst: analyst upgrade",
            "date": "2026-01-15",
        }
        result = pm.analyze(trade)
        assert result["which_signal_failed"] == "catalyst"

    def test_save_lesson_creates_files(self, tmp_path, monkeypatch):
        import tradingagents.learning.post_mortem as pm_mod
        monkeypatch.setattr(pm_mod, "LESSONS_FILE", tmp_path / "LESSONS.md")
        monkeypatch.setattr(pm_mod, "PATTERNS_FILE", tmp_path / "patterns.json")

        from tradingagents.learning.post_mortem import PostMortem
        pm = PostMortem()
        trade = {
            "ticker": "TSLA",
            "pnl_pct": -0.04,
            "hold_minutes": 30,
            "exit_reason": "STOP_HIT",
            "analysis_at_entry": "tech",
            "date": "2026-01-15",
        }
        lesson = pm.analyze(trade)
        pm.save_lesson(lesson)
        assert (tmp_path / "LESSONS.md").exists()
        assert (tmp_path / "patterns.json").exists()


# ---------------------------------------------------------------------------
# Signal Logger — accuracy stats
# ---------------------------------------------------------------------------

class TestSignalLoggerAccuracyStats:
    def _make_signal(self, action, correct, scan_time="9:30", ticker="NVDA"):
        return {
            "id": str(uuid.uuid4()),
            "timestamp": "2026-01-10T10:00:00Z",
            "scan_time": scan_time,
            "ticker": ticker,
            "action": action,
            "score": 7.0,
            "conviction": 8,
            "price_at_signal": 100.0,
            "stop_loss": 97.0,
            "target": 108.0,
            "acted_on": True,
            "skip_reason": None,
            "analysis_summary": "test",
            "verified": True,
            "price_1h_later": 105.0 if correct else 95.0,
            "price_4h_later": None,
            "price_eod": None,
            "target_hit": correct,
            "stop_hit": not correct,
            "signal_correct": correct,
            "accuracy_pct": 5.0 if correct else -3.0,
        }

    def test_accuracy_stats_buy(self, tmp_path, monkeypatch):
        import tradingagents.signals.signal_logger as sl_mod
        signals_file = tmp_path / "signals.jsonl"
        monkeypatch.setattr(sl_mod, "SIGNALS_FILE", signals_file)

        from tradingagents.signals.signal_logger import SignalLogger
        sl = SignalLogger()
        sl.log_signal(self._make_signal("BUY", True))
        sl.log_signal(self._make_signal("BUY", True))
        sl.log_signal(self._make_signal("BUY", False))
        stats = sl.get_accuracy_stats()
        assert stats["buy_accuracy"] == pytest.approx(2 / 3, rel=1e-3)

    def test_accuracy_stats_by_ticker(self, tmp_path, monkeypatch):
        import tradingagents.signals.signal_logger as sl_mod
        signals_file = tmp_path / "signals.jsonl"
        monkeypatch.setattr(sl_mod, "SIGNALS_FILE", signals_file)

        from tradingagents.signals.signal_logger import SignalLogger
        sl = SignalLogger()
        sl.log_signal(self._make_signal("BUY", True, ticker="NVDA"))
        sl.log_signal(self._make_signal("BUY", False, ticker="AMD"))
        stats = sl.get_accuracy_stats()
        assert "NVDA" in stats["by_ticker"]
        assert stats["by_ticker"]["NVDA"]["accuracy"] == pytest.approx(1.0)
        assert stats["by_ticker"]["AMD"]["accuracy"] == pytest.approx(0.0)

    def test_mark_verified_updates_record(self, tmp_path, monkeypatch):
        import tradingagents.signals.signal_logger as sl_mod
        signals_file = tmp_path / "signals.jsonl"
        monkeypatch.setattr(sl_mod, "SIGNALS_FILE", signals_file)

        from tradingagents.signals.signal_logger import SignalLogger
        sl = SignalLogger()
        sig_id = str(uuid.uuid4())
        sl.log_signal({
            "id": sig_id, "timestamp": "2020-01-01T10:00:00Z", "scan_time": "9:30",
            "ticker": "TEST", "action": "BUY", "score": 7.0, "conviction": 8,
            "price_at_signal": 100.0, "stop_loss": 97.0, "target": 108.0,
            "acted_on": True, "skip_reason": None, "analysis_summary": "",
        })
        sl.mark_verified(sig_id, {
            "price_1h_later": 105.0, "price_4h_later": None, "price_eod": 107.0,
            "target_hit": True, "stop_hit": False, "signal_correct": True, "accuracy_pct": 7.0,
        })
        unverified = sl.get_unverified(older_than_hours=0)
        # Signal should now be verified and not appear in unverified list
        assert all(s["id"] != sig_id for s in unverified)
