"""Console notifier — prints signals to terminal."""

from __future__ import annotations
from pro_trader.core.interfaces import NotifierPlugin
from pro_trader.models.signal import Signal


class ConsoleNotifier(NotifierPlugin):
    name = "console"
    version = "1.0.0"
    description = "Print trade signals to terminal"

    def notify(self, signal: Signal, context: dict | None = None) -> bool:
        icon = {"BUY": "+", "SELL": "-", "HOLD": "~", "PASS": "x"}.get(signal.direction.value, "?")
        threshold = "YES" if signal.meets_threshold else "NO"

        print(f"\n{'='*50}")
        print(f" [{icon}] {signal.direction.value} {signal.ticker}")
        print(f"     Score: {signal.score:.1f}/10 | Confidence: {signal.confidence}/10")
        print(f"     Price: ${signal.price:.2f} | Type: {signal.asset_type}")
        print(f"     Threshold: {threshold} | Source: {signal.source}")
        if signal.stop_loss:
            print(f"     Stop: ${signal.stop_loss:.2f} | Target: ${signal.take_profit:.2f}")
        if signal.metadata.get("risk_rejected_by"):
            print(f"     REJECTED by: {signal.metadata['risk_rejected_by']}")
            print(f"     Reason: {signal.metadata.get('risk_reason', '')}")
        print(f"{'='*50}\n")
        return True

    def notify_alert(self, alert: dict) -> bool:
        severity = alert.get("severity", "info").upper()
        print(f"[{severity}] {alert.get('message', '')}")
        return True
