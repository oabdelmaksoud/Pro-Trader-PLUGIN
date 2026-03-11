"""Tests for the Pro-Trader setup wizard (P0).

Covers: run_wizard, run_check, run_update, run_uninstall, all utility helpers.
All filesystem and subprocess calls are isolated via monkeypatch/tmp_path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pro_trader.cli.setup_wizard as wiz


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Redirect all wizard file paths to tmp_path so tests never touch real fs."""
    monkeypatch.setattr(wiz, "_REPO", tmp_path)
    monkeypatch.setattr(wiz, "_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(wiz, "_ENV_EXAMPLE", tmp_path / ".env.example")
    monkeypatch.setattr(wiz, "_USER_CONFIG_DIR", tmp_path / ".pro_trader")
    monkeypatch.setattr(wiz, "_USER_CONFIG", tmp_path / ".pro_trader" / "config.json")


# ── _mask ────────────────────────────────────────────────────────────────────

class TestMask:
    def test_empty(self):
        assert wiz._mask("") == "***"

    def test_short(self):
        assert wiz._mask("abcdef") == "***"

    def test_exactly_eight(self):
        assert wiz._mask("12345678") == "***"

    def test_nine_chars(self):
        assert wiz._mask("123456789") == "1234...6789"

    def test_long(self):
        assert wiz._mask("ABCDEFGHIJKLMNOP") == "ABCD...MNOP"


# ── _is_placeholder ──────────────────────────────────────────────────────────

class TestIsPlaceholder:
    @pytest.mark.parametrize("val", [
        "your_api_key_here", "your_alpaca_api_key_here",
        "changeme", "xxx", "replace_me", "todo", "", "   ",
    ])
    def test_placeholder_values(self, val):
        assert wiz._is_placeholder(val) is True

    @pytest.mark.parametrize("val", [
        "sk-abc123real", "PKABCDEF12345678", "actual_key_value",
    ])
    def test_real_values(self, val):
        assert wiz._is_placeholder(val) is False


# ── _test_command ────────────────────────────────────────────────────────────

class TestTestCommand:
    def test_success(self):
        ok, out = wiz._test_command(["echo", "hello"])
        assert ok is True
        assert "hello" in out

    def test_failure(self):
        ok, _ = wiz._test_command(["false"])
        assert ok is False

    def test_not_found(self):
        ok, out = wiz._test_command(["nonexistent_binary_xyz123"])
        assert ok is False
        assert "command not found" in out

    def test_timeout(self):
        ok, out = wiz._test_command(["sleep", "10"], timeout=1)
        assert ok is False
        assert "timed out" in out


# ── _load_env / _save_env ────────────────────────────────────────────────────

class TestEnvIO:
    def test_load_missing_file(self):
        assert wiz._load_env() == {}

    def test_roundtrip(self, tmp_path):
        env = {"KEY1": "val1", "KEY2": "val2"}
        wiz._save_env(env)
        assert wiz._load_env() == env

    def test_preserves_comments(self, tmp_path):
        (tmp_path / ".env.example").write_text(
            "# Comment line\nKEY1=placeholder\n# Another\nKEY2=placeholder\n"
        )
        wiz._save_env({"KEY1": "real1", "KEY2": "real2"})
        content = (tmp_path / ".env").read_text()
        assert "# Comment line" in content
        assert "# Another" in content
        assert "KEY1=real1" in content
        assert "KEY2=real2" in content

    def test_appends_new_keys(self, tmp_path):
        (tmp_path / ".env.example").write_text("KEY1=old\n")
        wiz._save_env({"KEY1": "new", "NEW_KEY": "extra"})
        loaded = wiz._load_env()
        assert loaded["KEY1"] == "new"
        assert loaded["NEW_KEY"] == "extra"

    def test_values_with_equals(self, tmp_path):
        env = {"URL": "https://api.example.com?foo=bar&baz=qux"}
        wiz._save_env(env)
        assert wiz._load_env()["URL"] == env["URL"]

    def test_blank_lines_skipped(self, tmp_path):
        (tmp_path / ".env").write_text("\n\n  \n# comment\nFOO=bar\n\nBAZ=qux\n")
        assert wiz._load_env() == {"FOO": "bar", "BAZ": "qux"}


# ── _load_user_config / _save_user_config ────────────────────────────────────

class TestUserConfigIO:
    def test_load_missing(self):
        assert wiz._load_user_config() == {}

    def test_roundtrip(self):
        cfg = {"llm_provider": "anthropic", "plugin_config": {"discord": {"enabled": True}}}
        wiz._save_user_config(cfg)
        assert wiz._load_user_config() == cfg

    def test_load_corrupted(self, tmp_path):
        config_dir = tmp_path / ".pro_trader"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("NOT JSON!!!")
        assert wiz._load_user_config() == {}


# ── _get_installed_version ───────────────────────────────────────────────────

class TestGetInstalledVersion:
    def test_cached(self):
        ver = wiz._get_installed_version(fresh=False)
        assert ver is None or isinstance(ver, str)

    def test_fresh(self):
        ver = wiz._get_installed_version(fresh=True)
        assert ver is None or isinstance(ver, str)

    def test_cached_and_fresh_match(self):
        """Without an intervening install, both should agree."""
        cached = wiz._get_installed_version(fresh=False)
        fresh = wiz._get_installed_version(fresh=True)
        assert cached == fresh


# ── _step_openclaw ───────────────────────────────────────────────────────────

class TestStepOpenclaw:
    def test_not_installed(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda x: None)
        result = wiz._step_openclaw()
        assert result["openclaw_available"] is False
        assert result["openclaw_version"] is None

    def test_installed_v2026(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/openclaw")
        monkeypatch.setattr(wiz, "_test_command", lambda cmd, **kw: (True, "openclaw v2026.3.8"))
        result = wiz._step_openclaw()
        assert result["openclaw_available"] is True
        assert "v2026.3.8" in result["openclaw_version"]

    def test_installed_old_version(self, monkeypatch, capsys):
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/openclaw")
        monkeypatch.setattr(wiz, "_test_command", lambda cmd, **kw: (True, "openclaw v2025.1.0"))
        result = wiz._step_openclaw()
        assert result["openclaw_available"] is True

    def test_version_check_fails(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/openclaw")
        calls = []

        def fake_cmd(cmd, **kw):
            calls.append(cmd)
            if "--version" in cmd:
                return False, "error"
            return True, "ok"

        monkeypatch.setattr(wiz, "_test_command", fake_cmd)
        result = wiz._step_openclaw()
        assert result["openclaw_available"] is False


# ── _step_discord ────────────────────────────────────────────────────────────

class TestStepDiscord:
    def test_skipped_when_unavailable(self):
        env = {"KEY": "val"}
        result = wiz._step_discord(env, {"openclaw_available": False})
        assert result == env

    @patch("pro_trader.cli.setup_wizard.Confirm")
    @patch("pro_trader.services.openclaw.send_discord", return_value=True)
    def test_sends_test_message(self, mock_send, mock_confirm):
        mock_confirm.ask.return_value = True
        env = {}
        wiz._step_discord(env, {"openclaw_available": True})
        mock_send.assert_called_once_with("war_room", "Pro-Trader setup wizard — test message")


# ── _step_broker ─────────────────────────────────────────────────────────────

class TestStepBroker:
    @patch("pro_trader.cli.setup_wizard.Confirm")
    @patch("pro_trader.cli.setup_wizard.Prompt")
    def test_fresh_install_paper(self, mock_prompt, mock_confirm):
        # First ask: broker selection ("1" = Alpaca)
        # Then: API key, secret key prompts
        mock_prompt.ask.side_effect = ["1", "PKABC123456789", "secretABC123456789"]
        mock_confirm.ask.return_value = True  # paper trading
        env, brokers, primary = wiz._step_broker({})
        assert env["ALPACA_API_KEY"] == "PKABC123456789"
        assert env["ALPACA_SECRET_KEY"] == "secretABC123456789"
        assert "paper" in env["ALPACA_BASE_URL"]
        assert brokers == ["alpaca"]
        assert primary == "alpaca"

    @patch("pro_trader.cli.setup_wizard.Confirm")
    @patch("pro_trader.cli.setup_wizard.Prompt")
    def test_existing_keys_no_update(self, mock_prompt, mock_confirm):
        mock_prompt.ask.side_effect = ["s"]  # skip broker setup
        mock_confirm.ask.return_value = False
        env = {"ALPACA_API_KEY": "PKABC123456789", "ALPACA_SECRET_KEY": "secretABC123456789"}
        result_env, brokers, primary = wiz._step_broker(env)
        assert result_env["ALPACA_API_KEY"] == "PKABC123456789"
        assert brokers == []


# ── _step_llm ────────────────────────────────────────────────────────────────

class TestStepLlm:
    @patch("pro_trader.cli.setup_wizard.Prompt")
    def test_select_anthropic(self, mock_prompt):
        mock_prompt.ask.side_effect = ["1", "sk-ant-test123456789"]
        env = wiz._step_llm({})
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-test123456789"
        assert env["_llm_provider"] == "anthropic"

    @patch("pro_trader.cli.setup_wizard.Prompt")
    def test_select_openai(self, mock_prompt):
        mock_prompt.ask.side_effect = ["2", "sk-openai-test123456789"]
        env = wiz._step_llm({})
        assert env["OPENAI_API_KEY"] == "sk-openai-test123456789"
        assert env["_llm_provider"] == "openai"


# ── run_check ────────────────────────────────────────────────────────────────

class TestRunCheck:
    def test_fresh_install(self, monkeypatch):
        """run_check should not crash on a fresh install with nothing configured."""
        monkeypatch.setattr("shutil.which", lambda x: None)
        # Mock ProTrader to avoid loading real plugins
        mock_trader = MagicMock()
        mock_trader.health.return_value = {"data": {"yfinance": {"status": "ok"}}}
        monkeypatch.setattr(
            "pro_trader.cli.setup_wizard.ProTrader",
            lambda **kw: mock_trader,
            raising=False,
        )
        wiz.run_check()  # Should not raise

    def test_with_env_file(self, tmp_path, monkeypatch):
        """run_check detects configured .env."""
        (tmp_path / ".env").write_text("ALPACA_API_KEY=PKABC123\nANTHROPIC_API_KEY=sk-ant-xyz\n")
        monkeypatch.setattr("shutil.which", lambda x: None)
        mock_trader = MagicMock()
        mock_trader.health.return_value = {}
        monkeypatch.setattr(
            "pro_trader.cli.setup_wizard.ProTrader",
            lambda **kw: mock_trader,
            raising=False,
        )
        wiz.run_check()  # Should not raise


# ── run_wizard ───────────────────────────────────────────────────────────────

class TestRunWizard:
    @patch("pro_trader.cli.setup_wizard._step_plugins", return_value={})
    @patch("pro_trader.cli.setup_wizard._step_discord", side_effect=lambda e, o: e)
    @patch("pro_trader.cli.setup_wizard._step_llm")
    @patch("pro_trader.cli.setup_wizard._step_broker")
    @patch("pro_trader.cli.setup_wizard._step_trader_profile")
    @patch("pro_trader.cli.setup_wizard._step_openclaw")
    @patch("pro_trader.cli.setup_wizard.Confirm")
    def test_full_flow_writes_files(
        self, mock_confirm, mock_oc, mock_profile, mock_broker, mock_llm,
        mock_discord, mock_plugins, tmp_path
    ):
        mock_oc.return_value = {"openclaw_available": False, "openclaw_version": None}
        mock_profile.return_value = {
            "account_size": 1000, "risk_tolerance": "moderate",
            "recovery_mode": False, "losses_to_recover": 0,
        }
        mock_broker.return_value = {
            "ALPACA_API_KEY": "PKABC",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        }
        mock_llm.return_value = {
            "ALPACA_API_KEY": "PKABC",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "_llm_provider": "anthropic",
        }
        mock_confirm.ask.return_value = True  # write files

        wiz.run_wizard()

        # .env should exist and not contain _llm_provider
        env = wiz._load_env()
        assert "ALPACA_API_KEY" in env
        assert "_llm_provider" not in env

        # User config should exist with llm_provider and trader_profile
        cfg = wiz._load_user_config()
        assert cfg["llm_provider"] == "anthropic"
        assert cfg["trader_profile"]["account_size"] == 1000
        assert cfg["account_value"] == 1000

    @patch("pro_trader.cli.setup_wizard._step_plugins", return_value={})
    @patch("pro_trader.cli.setup_wizard._step_discord", side_effect=lambda e, o: e)
    @patch("pro_trader.cli.setup_wizard._step_llm", side_effect=lambda e: e)
    @patch("pro_trader.cli.setup_wizard._step_broker", side_effect=lambda e: (e, [], ""))
    @patch("pro_trader.cli.setup_wizard._step_trader_profile")
    @patch("pro_trader.cli.setup_wizard._step_openclaw")
    @patch("pro_trader.cli.setup_wizard.Confirm")
    def test_cancel_no_write(
        self, mock_confirm, mock_oc, mock_profile, mock_broker, mock_llm,
        mock_discord, mock_plugins, tmp_path
    ):
        mock_oc.return_value = {"openclaw_available": False}
        mock_profile.return_value = {"account_size": 500, "recovery_mode": False}
        mock_confirm.ask.return_value = False  # cancel

        wiz.run_wizard()

        assert not (tmp_path / ".env").exists()
        assert not (tmp_path / ".pro_trader" / "config.json").exists()


# ── run_update ───────────────────────────────────────────────────────────────

class TestRunUpdate:
    @patch("pro_trader.cli.setup_wizard._is_editable_install", return_value=True)
    @patch("pro_trader.cli.setup_wizard._get_installed_version")
    @patch("pro_trader.cli.setup_wizard._test_command")
    def test_editable_path(self, mock_cmd, mock_ver, mock_edit, monkeypatch):
        mock_ver.side_effect = ["1.0.0", "1.1.0"]  # before, after
        mock_cmd.return_value = (True, "ok")
        monkeypatch.setattr("shutil.which", lambda x: None)
        mock_trader = MagicMock()
        mock_trader.health.return_value = {}
        monkeypatch.setattr(
            "pro_trader.cli.setup_wizard.ProTrader",
            lambda **kw: mock_trader,
            raising=False,
        )
        wiz.run_update()  # Should not raise

    @patch("pro_trader.cli.setup_wizard._is_editable_install", return_value=False)
    @patch("pro_trader.cli.setup_wizard._get_installed_version")
    @patch("pro_trader.cli.setup_wizard._test_command")
    def test_pip_path(self, mock_cmd, mock_ver, mock_edit, monkeypatch):
        mock_ver.side_effect = ["1.0.0", "1.0.0"]
        mock_cmd.return_value = (True, "ok")
        monkeypatch.setattr("shutil.which", lambda x: None)
        mock_trader = MagicMock()
        mock_trader.health.return_value = {}
        monkeypatch.setattr(
            "pro_trader.cli.setup_wizard.ProTrader",
            lambda **kw: mock_trader,
            raising=False,
        )
        wiz.run_update()  # Should not raise


# ── run_uninstall ────────────────────────────────────────────────────────────

class TestRunUninstall:
    @patch("pro_trader.cli.setup_wizard.Confirm")
    @patch("pro_trader.cli.setup_wizard._get_installed_version", return_value=None)
    def test_remove_config_files(self, mock_ver, mock_confirm, tmp_path):
        # Create artifacts
        (tmp_path / ".env").write_text("KEY=val\n")
        config_dir = tmp_path / ".pro_trader"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{}")

        # Say yes to everything
        mock_confirm.ask.return_value = True

        wiz.run_uninstall()

        assert not (config_dir / "config.json").exists()
        assert not (tmp_path / ".env").exists()

    @patch("pro_trader.cli.setup_wizard.Confirm")
    @patch("pro_trader.cli.setup_wizard._get_installed_version", return_value=None)
    def test_cancel(self, mock_ver, mock_confirm, tmp_path):
        (tmp_path / ".env").write_text("KEY=val\n")
        mock_confirm.ask.return_value = False  # cancel everything

        wiz.run_uninstall()

        # Nothing should be removed
        assert (tmp_path / ".env").exists()

    @patch("pro_trader.cli.setup_wizard.Confirm")
    @patch("pro_trader.cli.setup_wizard._get_installed_version", return_value="1.0.0")
    @patch("pro_trader.cli.setup_wizard._test_command", return_value=(True, "ok"))
    def test_pip_uninstall(self, mock_cmd, mock_ver, mock_confirm, tmp_path):
        mock_confirm.ask.return_value = True
        wiz.run_uninstall()
        # Verify pip uninstall was called
        mock_cmd.assert_called()

    @patch("pro_trader.cli.setup_wizard.Confirm")
    @patch("pro_trader.cli.setup_wizard._get_installed_version", return_value=None)
    def test_removes_logs_dir(self, mock_ver, mock_confirm, tmp_path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        (logs_dir / "test.log").write_text("log data")
        mock_confirm.ask.return_value = True

        wiz.run_uninstall()

        assert not logs_dir.exists()
