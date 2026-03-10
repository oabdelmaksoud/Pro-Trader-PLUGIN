"""
OpenClaw Integration Layer — centralized messaging for Pro-Trader.

Compatible with openclaw v2026.3.8 (latest stable, March 9 2026).

OpenClaw is used exclusively as a Discord messaging bridge:
  - `openclaw message send --channel discord --target <ID> --message <TEXT>`
  - `openclaw cron list --json` / `openclaw cron trigger <ID>`

Version history addressed:
  - v2026.3.8: backup/restore, TUI theme detect, ACP provenance, Podman SELinux,
               cron restart catch-up with missed-job replay limits, --version now
               includes git commit hash. No changes to `message send` CLI.
  - v2026.3.7: gateway.auth.mode must be explicit (only affects gateway, not CLI)
  - v2026.3.2: tools.profile defaults to "messaging" (only affects agent mode),
               registerHttpHandler removed (we don't use plugin routes)
  - v2026.2.26: heartbeat DM delivery default changed (doesn't affect CLI send)

All changes are gateway/agent-level — the `message send` CLI is stable across all versions.
The `cron list --json` and `cron trigger` CLIs are also stable (v2026.3.8 adds replay limits
for missed cron jobs on restart, which improves our wake_recovery.py behavior).

Usage:
    from pro_trader.services.openclaw import send_discord, send_discord_async

    send_discord("1469763123010342953", "Hello from Pro-Trader!")
    send_discord_async("1469763123010342953", "Background message")
"""

from __future__ import annotations
import json
import logging
import subprocess
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# ── Discord Channel Registry ────────────────────────────────────────────────
CHANNELS = {
    "war_room":         "1469763123010342953",
    "paper_trades":     "1468597633756037385",
    "winning_trades":   "1468620383019077744",
    "losing_trades":    "1468620412849229825",
    "cooper_study":     "1468621074999541810",
    "gamespoofer":      "1469519503174926568",
    "trading_chat":     "1467904044675629258",
}

# Cache openclaw CLI availability
_openclaw_available: Optional[bool] = None


def is_available() -> bool:
    """Check if openclaw CLI is installed and accessible."""
    global _openclaw_available
    if _openclaw_available is None:
        _openclaw_available = shutil.which("openclaw") is not None
    return _openclaw_available


def send_discord(channel_id: str, message: str, timeout: int = 15) -> bool:
    """
    Send a Discord message via openclaw CLI (blocking).

    Compatible with openclaw v2026.3.8 (latest stable).
    Gracefully returns False if openclaw is not available.

    Args:
        channel_id: Discord channel ID or channel name from CHANNELS dict
        message: Message text (supports Discord markdown)
        timeout: Subprocess timeout in seconds
    """
    # Resolve channel name to ID
    if channel_id in CHANNELS:
        channel_id = CHANNELS[channel_id]

    if not is_available():
        logger.debug("openclaw not available — skipping Discord message")
        return False

    try:
        result = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target", channel_id,
             "--message", message],
            capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        if result.returncode != 0:
            logger.warning(f"openclaw send failed (rc={result.returncode}): {result.stderr[:200]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning(f"openclaw send timed out after {timeout}s")
        return False
    except Exception as e:
        logger.warning(f"openclaw send error: {e}")
        return False


def send_discord_async(channel_id: str, message: str) -> Optional[subprocess.Popen]:
    """
    Send a Discord message via openclaw CLI (non-blocking).

    Returns the Popen process or None if unavailable.
    """
    if channel_id in CHANNELS:
        channel_id = CHANNELS[channel_id]

    if not is_available():
        return None

    try:
        proc = subprocess.Popen(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target", channel_id,
             "--message", message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc
    except Exception as e:
        logger.warning(f"openclaw async send error: {e}")
        return None


def list_cron_jobs() -> list[dict]:
    """
    List openclaw cron jobs.

    Compatible with openclaw v2026.3.8 (latest stable).
    """
    if not is_available():
        return []

    try:
        result = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return []
    except Exception as e:
        logger.warning(f"openclaw cron list failed: {e}")
        return []


def trigger_cron_job(job_id: str) -> bool:
    """Trigger a specific openclaw cron job."""
    if not is_available():
        return False

    try:
        result = subprocess.run(
            ["openclaw", "cron", "trigger", job_id],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"openclaw cron trigger failed: {e}")
        return False


def check_version() -> Optional[str]:
    """Get openclaw version string."""
    if not is_available():
        return None
    try:
        result = subprocess.run(
            ["openclaw", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def health_check() -> dict:
    """Check openclaw health for the plugin system."""
    available = is_available()
    version = check_version() if available else None
    return {
        "available": available,
        "version": version,
        "status": "ok" if available else "not_installed",
        "channels": len(CHANNELS),
        "notes": [
            "Compatible with openclaw v2026.3.8 (latest stable, March 9 2026)",
            "Used for Discord messaging only (not agent/oracle)",
            "Graceful degradation when unavailable",
        ],
    }
