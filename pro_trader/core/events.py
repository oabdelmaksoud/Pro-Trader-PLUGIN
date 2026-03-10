"""
Event Bus — pub/sub for plugin communication.

Plugins don't import each other. Instead they emit and listen for events.

Usage:
    bus = EventBus()
    bus.on("signal.new", my_handler)
    bus.emit("signal.new", signal=signal)

Built-in events:
    data.quote          — new quote received
    data.technicals     — technicals calculated
    analyst.report      — analyst finished report
    signal.new          — new trade signal
    signal.approved     — signal passed risk checks
    signal.rejected     — signal failed risk checks
    order.submitted     — order sent to broker
    order.filled        — order filled
    monitor.alert       — monitor emitted alert
    risk.halt           — risk system halted trading
    risk.resume         — risk system resumed trading
    pipeline.start      — pipeline started for a ticker
    pipeline.complete   — pipeline finished
"""

from __future__ import annotations
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[..., Any]


class EventBus:
    """Simple synchronous event bus for plugin communication."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: list[dict] = []
        self._max_history: int = 1000

    def on(self, event: str, handler: EventHandler) -> None:
        """Subscribe to an event."""
        self._handlers[event].append(handler)

    def off(self, event: str, handler: EventHandler) -> None:
        """Unsubscribe from an event."""
        if event in self._handlers:
            self._handlers[event] = [h for h in self._handlers[event] if h is not handler]

    def emit(self, event: str, **kwargs) -> list[Any]:
        """
        Emit an event. All subscribed handlers are called synchronously.
        Returns list of handler return values.
        """
        results = []

        # Record in history
        self._history.append({"event": event, "kwargs_keys": list(kwargs.keys())})
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Exact match handlers
        for handler in self._handlers.get(event, []):
            try:
                result = handler(**kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Event handler error for '{event}': {e}")

        # Wildcard handlers (e.g., "signal.*" catches "signal.new")
        prefix = event.rsplit(".", 1)[0] + ".*" if "." in event else ""
        if prefix and prefix in self._handlers:
            for handler in self._handlers[prefix]:
                try:
                    result = handler(event=event, **kwargs)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Wildcard handler error for '{event}': {e}")

        # Global wildcard "*"
        for handler in self._handlers.get("*", []):
            try:
                result = handler(event=event, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Global handler error for '{event}': {e}")

        return results

    def clear(self, event: str | None = None) -> None:
        """Clear handlers for an event, or all handlers if event is None."""
        if event:
            self._handlers.pop(event, None)
        else:
            self._handlers.clear()

    @property
    def events(self) -> list[str]:
        """List all events with active handlers."""
        return list(self._handlers.keys())

    @property
    def history(self) -> list[dict]:
        """Recent event history."""
        return self._history.copy()
