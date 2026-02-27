"""
CooperCorp PRJ-002 — Signal Tracking Package
Tracks every signal generated: BUY, SELL, HOLD, PASS — acted on or not.
Retroactively verifies if signals were correct to enable continuous learning.
"""
from tradingagents.signals.signal_logger import SignalLogger
from tradingagents.signals.signal_verifier import SignalVerifier

__all__ = ["SignalLogger", "SignalVerifier"]
