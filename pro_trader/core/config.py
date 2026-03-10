"""
Unified Config — cascading configuration system.

Priority (highest wins):
  1. CLI arguments / explicit overrides
  2. Environment variables (PROTRADER_*)
  3. User config file (~/.pro_trader/config.yaml or config/strategy.json)
  4. Plugin defaults
  5. Built-in defaults
"""

from __future__ import annotations
import json
import os
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    # ── Core ──────────────────────────────────────────────────────────
    "project_dir": str(Path(__file__).resolve().parent.parent.parent),
    "results_dir": "./results",
    "logs_dir": "./logs",

    # ── LLM ───────────────────────────────────────────────────────────
    "llm_provider": "anthropic",
    "deep_think_llm": "claude-opus-4-6",
    "quick_think_llm": "claude-sonnet-4-6",
    "backend_url": None,
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,

    # ── Trading ───────────────────────────────────────────────────────
    "account_value": 500,
    "max_positions": 3,
    "score_threshold": 7.0,
    "conviction_min": 7,
    "risk_per_trade_pct": 0.02,

    # ── Futures ───────────────────────────────────────────────────────
    "futures": {
        "enabled": True,
        "margin_buffer": 1.5,
        "max_contracts": 1,
        "max_margin_pct": 0.60,
        "stop_ticks_default": 20,
        "target_ticks_default": 40,
    },

    # ── Plugins ───────────────────────────────────────────────────────
    "plugins": {
        "data": ["yfinance", "futures"],
        "analyst": ["flash", "macro", "pulse"],
        "strategy": ["cooper_scorer"],
        "broker": ["alpaca"],
        "risk": ["circuit_breaker", "kelly_sizer", "portfolio_heat"],
        "monitor": ["news", "fomc", "futures"],
        "notifier": ["discord", "console"],
    },

    # ── Per-plugin config ─────────────────────────────────────────────
    "plugin_config": {
        "alpaca": {"paper": True},
        "discord": {
            "war_room_channel": "1469763123010342953",
        },
        "circuit_breaker": {
            "max_drawdown_pct": 5.0,
            "max_daily_loss": 3.0,
        },
    },

    # ── Data vendors (legacy compatibility) ───────────────────────────
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    },
}


class Config:
    """Cascading configuration with env var overrides and file loading."""

    def __init__(self, overrides: dict | None = None):
        self._data = self._deep_copy(DEFAULT_CONFIG)
        self._load_env_vars()
        self._load_config_files()
        if overrides:
            self._deep_merge(self._data, overrides)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value. Supports dot notation: 'futures.margin_buffer'."""
        parts = key.split(".")
        val = self._data
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return default
        return val

    def set(self, key: str, value: Any) -> None:
        """Set a config value. Supports dot notation."""
        parts = key.split(".")
        target = self._data
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value

    @property
    def data(self) -> dict:
        """Full config dict (read-only copy)."""
        return self._deep_copy(self._data)

    def to_legacy_config(self) -> dict:
        """Convert to legacy DEFAULT_CONFIG format for tradingagents compatibility."""
        from tradingagents.default_config import DEFAULT_CONFIG as LEGACY
        legacy = self._deep_copy(LEGACY)
        legacy["llm_provider"] = self._data.get("llm_provider", "anthropic")
        legacy["deep_think_llm"] = self._data.get("deep_think_llm", "claude-opus-4-6")
        legacy["quick_think_llm"] = self._data.get("quick_think_llm", "claude-sonnet-4-6")
        legacy["max_debate_rounds"] = self._data.get("max_debate_rounds", 2)
        legacy["max_risk_discuss_rounds"] = self._data.get("max_risk_discuss_rounds", 2)
        if self._data.get("backend_url"):
            legacy["backend_url"] = self._data["backend_url"]
        legacy["data_vendors"] = self._data.get("data_vendors", legacy["data_vendors"])
        return legacy

    def _load_env_vars(self) -> None:
        """Load PROTRADER_* environment variables."""
        prefix = "PROTRADER_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower().replace("__", ".")
                # Auto-convert types
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif value.isdigit():
                    value = int(value)
                else:
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                self.set(config_key, value)

    def _load_config_files(self) -> None:
        """Load config from known file locations."""
        project_dir = Path(self._data["project_dir"])
        config_paths = [
            project_dir / "config" / "strategy.json",
            project_dir / "config" / "plugins.json",
            Path.home() / ".pro_trader" / "config.json",
        ]

        for path in config_paths:
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    self._deep_merge(self._data, data)
                    logger.debug(f"Loaded config from {path}")
                except Exception as e:
                    logger.warning(f"Failed to load config from {path}: {e}")

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge override into base."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Config._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    @staticmethod
    def _deep_copy(d: dict) -> dict:
        """Simple deep copy for JSON-serializable dicts."""
        return json.loads(json.dumps(d))

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __repr__(self) -> str:
        return f"Config({len(self._data)} keys)"
