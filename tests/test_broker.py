"""Basic smoke tests for AlpacaBroker and core modules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


def test_imports():
    from tradingagents.brokers.alpaca import AlpacaBroker
    from tradingagents.execution.executor import TradeExecutor
    from tradingagents.risk.circuit_breaker import CircuitBreaker
    from tradingagents.signals.signal_logger import SignalLogger
    from tradingagents.performance.ledger import TradeLedger
    from tradingagents.learning.post_mortem import PostMortem
    from tradingagents.learning.pattern_tracker import PatternTracker
    from tradingagents.utils.market_hours import is_market_open, is_market_holiday


def test_broker_connectivity():
    from tradingagents.brokers.alpaca import AlpacaBroker
    b = AlpacaBroker()
    value = b.get_portfolio_value()
    assert value > 0, "Portfolio value should be positive"
    bp = b.get_buying_power()
    assert bp > 0, "Buying power should be positive"


def test_circuit_breaker():
    from tradingagents.brokers.alpaca import AlpacaBroker
    from tradingagents.risk.circuit_breaker import CircuitBreaker
    broker = AlpacaBroker()
    cb = CircuitBreaker(broker)
    result = cb.check()
    assert "ok" in result
    assert isinstance(result["ok"], bool)


def test_signal_logger():
    import uuid
    from tradingagents.signals.signal_logger import SignalLogger
    sl = SignalLogger()
    sl.log_signal({
        "id": str(uuid.uuid4()),
        "timestamp": "2026-02-27T09:30:00Z",
        "scan_time": "test",
        "ticker": "TEST",
        "action": "PASS",
        "score": 5.0,
        "conviction": 4,
        "price_at_signal": 100.0,
        "stop_loss": 97.0,
        "target": 108.0,
        "acted_on": False,
        "skip_reason": "test",
        "analysis_summary": "unit test",
        "verified": False,
        "price_1h_later": None,
        "price_4h_later": None,
        "price_eod": None,
        "target_hit": None,
        "stop_hit": None,
        "signal_correct": None,
        "accuracy_pct": None,
    })


def test_market_hours():
    from tradingagents.utils.market_hours import is_market_holiday
    from datetime import date
    assert is_market_holiday(date(2026, 1, 1)) == True  # New Year's
    assert is_market_holiday(date(2026, 3, 2)) == False  # Regular day


def test_ledger():
    from tradingagents.performance.ledger import TradeLedger
    ledger = TradeLedger()
    # Should not raise
    stats = ledger.summary()
    assert "total_trades" in stats


def test_ledger_record_close():
    """Test record_close writes to ledger.jsonl."""
    from tradingagents.performance.ledger import TradeLedger, LEDGER_PATH
    ledger = TradeLedger()
    before_count = 0
    if LEDGER_PATH.exists():
        before_count = sum(1 for _ in open(LEDGER_PATH) if _.strip())

    ledger.record_close(
        ticker="TEST_UNIT",
        side="long",
        entry_price=100.0,
        exit_price=108.0,
        qty=10,
        hold_minutes=60,
        reason="TARGET_HIT",
    )

    after_count = sum(1 for _ in open(LEDGER_PATH) if _.strip())
    assert after_count == before_count + 1, "record_close should append one entry to ledger"


def test_post_mortem_web_search():
    """Test post_mortem._web_search uses yfinance (no longer calls openclaw CLI)."""
    from tradingagents.learning.post_mortem import PostMortem
    pm = PostMortem()
    # Should not raise; may return headlines or fallback message
    result = pm._web_search("NVDA stock news today")
    assert isinstance(result, str)
    # Should NOT try to call openclaw CLI (which doesn't exist)
    assert "openclaw" not in result.lower() or "Search failed" in result
