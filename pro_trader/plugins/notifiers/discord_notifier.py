"""Discord notifier — sends signals via openclaw or webhook."""

from __future__ import annotations
import logging
from datetime import datetime

from pro_trader.core.interfaces import NotifierPlugin
from pro_trader.models.signal import Signal
from pro_trader.services.openclaw import send_discord, CHANNELS

logger = logging.getLogger(__name__)


class DiscordNotifier(NotifierPlugin):
    name = "discord"
    version = "1.0.0"
    description = "Send trade signals to Discord via openclaw (v2026.3.8 compatible)"

    def __init__(self):
        self._war_room_channel = CHANNELS.get("war_room", "")
        self._trades_channel = CHANNELS.get("paper_trades", "")

    def configure(self, config: dict) -> None:
        self._war_room_channel = config.get("war_room_channel", self._war_room_channel)
        self._trades_channel = config.get("trades_channel", self._trades_channel)

    def notify(self, signal: Signal, context: dict | None = None) -> bool:
        if not self._war_room_channel:
            logger.debug("Discord: no channel configured — skipping")
            return False

        channel = context.get("channel", self._war_room_channel) if context else self._war_room_channel
        msg = self._format_signal(signal)
        return send_discord(channel, msg)

    def notify_alert(self, alert: dict) -> bool:
        if not self._war_room_channel:
            return False
        msg = f"**{alert.get('severity', 'INFO').upper()}**: {alert.get('message', '')}"
        return send_discord(self._war_room_channel, msg)

    @staticmethod
    def _format_signal(signal: Signal) -> str:
        icon = {"BUY": "+", "SELL": "-", "HOLD": "~", "PASS": "x"}.get(signal.direction.value, "?")
        now = datetime.now().strftime("%I:%M %p ET")

        parts = [
            f"**[{icon}] {signal.direction.value} {signal.ticker}** | {now}",
            f"Score: {signal.score:.1f}/10 | Confidence: {signal.confidence}/10",
            f"Price: ${signal.price:.2f} | Type: {signal.asset_type}",
        ]

        if signal.stop_loss:
            parts.append(f"Stop: ${signal.stop_loss:.2f} | Target: ${signal.take_profit:.2f}")

        if signal.meets_threshold:
            parts.append("**THRESHOLD MET** — Trade active")
        else:
            parts.append("Below threshold — no trade")

        parts.append("— Cooper | Pro-Trader Plugin")
        return "\n".join(parts)
