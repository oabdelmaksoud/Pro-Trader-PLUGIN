"""
CooperCorp PRJ-002 — Strategy Configuration Loader
Single source of truth for all strategy parameters.
"""
import json
from pathlib import Path
from functools import lru_cache

CONFIG_FILE = Path(__file__).parent.parent.parent / "config" / "strategy.json"


@lru_cache(maxsize=1)
def load_strategy() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def get_position_pct(conviction: int) -> float:
    """Returns position size % based on conviction score."""
    cfg = load_strategy()
    scaling = cfg["position"]["conviction_scaling"]
    # Find matching conviction tier (round down to nearest)
    for k in sorted(scaling.keys(), reverse=True):
        if conviction >= int(k):
            return scaling[k]
    return cfg["position"]["default_pct"]


def get_stop_pct() -> float:
    return load_strategy()["position"]["stop_pct"]


def get_target_pct() -> float:
    return load_strategy()["position"]["target_pct"]


def get_vix_multiplier(vix: float) -> float:
    thresholds = load_strategy()["risk"]["vix_thresholds"]
    for tier in ["low", "medium", "high"]:
        if vix <= thresholds[tier]["vix_max"]:
            return thresholds[tier]["size_multiplier"]
    return 0.4


def get_sector(symbol: str) -> str | None:
    sectors = load_strategy()["risk"]["correlation_sectors"]
    for sector, tickers in sectors.items():
        if symbol.upper() in tickers:
            return sector
    return None


def get_current_vix() -> float:
    """Fetch current VIX from yfinance."""
    try:
        import yfinance as yf
        vix = yf.Ticker("^VIX")
        info = vix.fast_info
        return float(info.last_price or 20.0)
    except Exception:
        return 20.0  # Default to low-vol assumption on failure
