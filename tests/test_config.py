"""Tests for config.py — cascading configuration system (P0).

Covers: defaults, file loading, env var overrides, dot notation, deep merge, type coercion.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pro_trader.core.config import Config, DEFAULT_CONFIG


# ── Defaults ─────────────────────────────────────────────────────────────────

class TestDefaults:
    def test_has_required_keys(self):
        cfg = Config()
        assert cfg.get("score_threshold") == 7.0
        assert cfg.get("llm_provider") == "anthropic"
        assert cfg.get("account_value") == 500
        assert cfg.get("max_positions") == 3

    def test_nested_defaults(self):
        cfg = Config()
        assert cfg.get("futures.enabled") is True
        assert cfg.get("futures.margin_buffer") == 1.5

    def test_plugin_config(self):
        cfg = Config()
        assert cfg.get("plugin_config.alpaca.paper") is True

    def test_missing_key_returns_default(self):
        cfg = Config()
        assert cfg.get("nonexistent") is None
        assert cfg.get("nonexistent", 42) == 42

    def test_data_returns_copy(self):
        cfg = Config()
        d1 = cfg.data
        d2 = cfg.data
        assert d1 == d2
        d1["mutated"] = True
        assert "mutated" not in cfg.data


# ── Overrides ────────────────────────────────────────────────────────────────

class TestOverrides:
    def test_simple_override(self):
        cfg = Config(overrides={"score_threshold": 8.5})
        assert cfg.get("score_threshold") == 8.5

    def test_nested_override(self):
        cfg = Config(overrides={"futures": {"margin_buffer": 2.0}})
        assert cfg.get("futures.margin_buffer") == 2.0
        # Other futures keys should still have defaults
        assert cfg.get("futures.enabled") is True

    def test_set_and_get(self):
        cfg = Config()
        cfg.set("custom.nested.key", "value")
        assert cfg.get("custom.nested.key") == "value"


# ── Env var loading ──────────────────────────────────────────────────────────

class TestEnvVars:
    def test_string_var(self, monkeypatch):
        monkeypatch.setenv("PROTRADER_LLM_PROVIDER", "openai")
        cfg = Config()
        assert cfg.get("llm_provider") == "openai"

    def test_bool_true(self, monkeypatch):
        monkeypatch.setenv("PROTRADER_FUTURES__ENABLED", "true")
        cfg = Config()
        assert cfg.get("futures.enabled") is True

    def test_bool_false(self, monkeypatch):
        monkeypatch.setenv("PROTRADER_FUTURES__ENABLED", "false")
        cfg = Config()
        assert cfg.get("futures.enabled") is False

    def test_int_var(self, monkeypatch):
        monkeypatch.setenv("PROTRADER_MAX_POSITIONS", "5")
        cfg = Config()
        assert cfg.get("max_positions") == 5

    def test_float_var(self, monkeypatch):
        monkeypatch.setenv("PROTRADER_SCORE_THRESHOLD", "8.5")
        cfg = Config()
        assert cfg.get("score_threshold") == 8.5

    def test_dot_notation_via_double_underscore(self, monkeypatch):
        monkeypatch.setenv("PROTRADER_PLUGIN_CONFIG__DISCORD__ENABLED", "true")
        cfg = Config()
        assert cfg.get("plugin_config.discord.enabled") is True

    def test_non_protrader_vars_ignored(self, monkeypatch):
        monkeypatch.setenv("OTHER_VAR", "ignored")
        cfg = Config()
        assert cfg.get("other_var") is None


# ── File loading ─────────────────────────────────────────────────────────────

class TestFileLoading:
    def test_loads_strategy_json(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "strategy.json").write_text(json.dumps({"score_threshold": 9.0}))
        monkeypatch.setitem(DEFAULT_CONFIG, "project_dir", str(tmp_path))
        cfg = Config()
        assert cfg.get("score_threshold") == 9.0

    def test_ignores_missing_files(self, tmp_path, monkeypatch):
        monkeypatch.setitem(DEFAULT_CONFIG, "project_dir", str(tmp_path))
        cfg = Config()  # Should not crash
        assert cfg.get("score_threshold") is not None

    def test_ignores_invalid_json(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "strategy.json").write_text("NOT JSON!!!")
        monkeypatch.setitem(DEFAULT_CONFIG, "project_dir", str(tmp_path))
        cfg = Config()  # Should not crash
        assert cfg.get("score_threshold") is not None


# ── Deep merge ───────────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_override_scalar(self):
        base = {"a": 1, "b": 2}
        Config._deep_merge(base, {"a": 10})
        assert base["a"] == 10
        assert base["b"] == 2

    def test_merge_nested(self):
        base = {"a": {"x": 1, "y": 2}}
        Config._deep_merge(base, {"a": {"y": 20, "z": 30}})
        assert base["a"]["x"] == 1
        assert base["a"]["y"] == 20
        assert base["a"]["z"] == 30

    def test_override_dict_with_scalar(self):
        base = {"a": {"x": 1}}
        Config._deep_merge(base, {"a": "flat"})
        assert base["a"] == "flat"


# ── to_legacy_config ─────────────────────────────────────────────────────────

class TestToLegacyConfig:
    def test_maps_llm_provider(self):
        cfg = Config(overrides={"llm_provider": "openai"})
        legacy = cfg.to_legacy_config()
        assert legacy["llm_provider"] == "openai"

    def test_maps_models(self):
        cfg = Config()
        legacy = cfg.to_legacy_config()
        assert "deep_think_llm" in legacy
        assert "quick_think_llm" in legacy


# ── Container protocol ───────────────────────────────────────────────────────

class TestContainerProtocol:
    def test_getitem(self):
        cfg = Config()
        assert cfg["score_threshold"] == 7.0

    def test_contains(self):
        cfg = Config()
        assert "score_threshold" in cfg
        assert "nonexistent_key_xyz" not in cfg

    def test_repr(self):
        cfg = Config()
        assert "Config(" in repr(cfg)
