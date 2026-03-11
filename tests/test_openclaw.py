"""Tests for openclaw.py — the centralized OpenClaw integration layer (P0).

Covers: is_available, send_discord, send_discord_async, list_cron_jobs,
        trigger_cron_job, check_version, health_check, graceful degradation.
All subprocess calls are mocked.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import pro_trader.services.openclaw as oc


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the module-level availability cache between tests."""
    oc._openclaw_available = None
    yield
    oc._openclaw_available = None


# ── is_available ─────────────────────────────────────────────────────────────

class TestIsAvailable:
    @patch("shutil.which", return_value="/usr/bin/openclaw")
    def test_found(self, mock_which):
        assert oc.is_available() is True

    @patch("shutil.which", return_value=None)
    def test_not_found(self, mock_which):
        assert oc.is_available() is False

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    def test_caches_result(self, mock_which):
        oc.is_available()
        oc.is_available()
        mock_which.assert_called_once()


# ── send_discord ─────────────────────────────────────────────────────────────

class TestSendDiscord:
    @patch("shutil.which", return_value=None)
    def test_graceful_when_unavailable(self, _):
        assert oc.send_discord("123", "hello") is False

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_success(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        assert oc.send_discord("123", "test message") is True
        args = mock_run.call_args[0][0]
        assert args == [
            "openclaw", "message", "send",
            "--channel", "discord",
            "--target", "123",
            "--message", "test message",
        ]

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_resolves_channel_name(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0)
        oc.send_discord("war_room", "msg")
        args = mock_run.call_args[0][0]
        # args: ["openclaw", "message", "send", "--channel", "discord", "--target", <ID>, ...]
        assert oc.CHANNELS["war_room"] in args

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_nonzero_exit(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        assert oc.send_discord("123", "msg") is False

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=15))
    def test_timeout(self, mock_run, _):
        assert oc.send_discord("123", "msg") is False

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run", side_effect=OSError("broken pipe"))
    def test_exception(self, mock_run, _):
        assert oc.send_discord("123", "msg") is False


# ── send_discord_async ───────────────────────────────────────────────────────

class TestSendDiscordAsync:
    @patch("shutil.which", return_value=None)
    def test_returns_none_when_unavailable(self, _):
        assert oc.send_discord_async("123", "msg") is None

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.Popen")
    def test_returns_popen(self, mock_popen, _):
        proc = MagicMock()
        mock_popen.return_value = proc
        result = oc.send_discord_async("123", "msg")
        assert result is proc

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.Popen", side_effect=OSError("fail"))
    def test_exception_returns_none(self, mock_popen, _):
        assert oc.send_discord_async("123", "msg") is None


# ── list_cron_jobs ───────────────────────────────────────────────────────────

class TestListCronJobs:
    @patch("shutil.which", return_value=None)
    def test_returns_empty_when_unavailable(self, _):
        assert oc.list_cron_jobs() == []

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_parses_json(self, mock_run, _):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='[{"id": "j1", "schedule": "* * * * *"}]',
        )
        jobs = oc.list_cron_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "j1"

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_nonzero_exit(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert oc.list_cron_jobs() == []

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run", side_effect=Exception("boom"))
    def test_exception(self, mock_run, _):
        assert oc.list_cron_jobs() == []


# ── trigger_cron_job ─────────────────────────────────────────────────────────

class TestTriggerCronJob:
    @patch("shutil.which", return_value=None)
    def test_returns_false_when_unavailable(self, _):
        assert oc.trigger_cron_job("j1") is False

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_success(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0)
        assert oc.trigger_cron_job("j1") is True
        args = mock_run.call_args[0][0]
        assert args == ["openclaw", "cron", "trigger", "j1"]

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_failure(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=1)
        assert oc.trigger_cron_job("j1") is False


# ── check_version ────────────────────────────────────────────────────────────

class TestCheckVersion:
    @patch("shutil.which", return_value=None)
    def test_returns_none_when_unavailable(self, _):
        assert oc.check_version() is None

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_returns_version(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0, stdout="openclaw v2026.3.8\n")
        assert oc.check_version() == "openclaw v2026.3.8"


# ── health_check ─────────────────────────────────────────────────────────────

class TestHealthCheck:
    @patch("shutil.which", return_value=None)
    def test_not_installed(self, _):
        h = oc.health_check()
        assert h["available"] is False
        assert h["status"] == "not_installed"
        assert h["version"] is None

    @patch("shutil.which", return_value="/usr/bin/openclaw")
    @patch("subprocess.run")
    def test_installed(self, mock_run, _):
        mock_run.return_value = MagicMock(returncode=0, stdout="openclaw v2026.3.8\n")
        h = oc.health_check()
        assert h["available"] is True
        assert h["status"] == "ok"
        assert h["channels"] == len(oc.CHANNELS)


# ── CHANNELS registry ────────────────────────────────────────────────────────

class TestChannels:
    def test_all_ids_are_strings(self):
        for name, cid in oc.CHANNELS.items():
            assert isinstance(cid, str), f"{name} channel ID should be str"
            assert cid.isdigit(), f"{name} channel ID should be numeric"

    def test_war_room_exists(self):
        assert "war_room" in oc.CHANNELS
