"""
CooperCorp PRJ-002 — Real-Time Candle Builder
Aggregates raw WebSocket trade ticks into multi-timeframe OHLCV candles.

Timeframes built simultaneously:
  1m, 5m, 15m, 1h, 4h, 1d

Each candle: {open, high, low, close, volume, timestamp, complete}
Completed candles are appended to rolling history (max 500 per TF).
Persists to logs/candles/{SYMBOL}_{timeframe}.json for other modules.

Usage:
  builder = CandleBuilder("NVDA")
  builder.on_tick(price=135.50, size=100, timestamp=time.time())
  candles_5m = builder.get_candles("5m", count=20)
"""
import json
import time
from collections import deque
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent
CANDLES_DIR = REPO_ROOT / "logs" / "candles"

# Timeframe durations in seconds
TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

MAX_CANDLES = 500  # per timeframe


class Candle:
    """Single OHLCV candle."""
    __slots__ = ("open", "high", "low", "close", "volume", "timestamp", "complete")

    def __init__(self, price: float, volume: int, timestamp: float):
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        self.volume = volume
        self.timestamp = timestamp
        self.complete = False

    def update(self, price: float, volume: int):
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume

    def to_dict(self) -> dict:
        return {
            "o": round(self.open, 4),
            "h": round(self.high, 4),
            "l": round(self.low, 4),
            "c": round(self.close, 4),
            "v": self.volume,
            "t": self.timestamp,
            "complete": self.complete,
        }

    @staticmethod
    def from_dict(d: dict) -> "Candle":
        c = Candle(d["o"], d["v"], d["t"])
        c.high = d["h"]
        c.low = d["l"]
        c.close = d["c"]
        c.complete = d.get("complete", True)
        return c

    @property
    def body(self) -> float:
        """Absolute body size."""
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        """Full high-low range."""
        return self.high - self.low

    @property
    def upper_shadow(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


class CandleBuilder:
    """
    Builds multi-timeframe candles from raw trade ticks for a single symbol.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        # {timeframe: deque of completed Candle objects}
        self.history: dict[str, deque] = {
            tf: deque(maxlen=MAX_CANDLES) for tf in TIMEFRAMES
        }
        # {timeframe: current (in-progress) Candle}
        self.current: dict[str, Optional[Candle]] = {tf: None for tf in TIMEFRAMES}
        self._load_history()

    def _candle_file(self, tf: str) -> Path:
        return CANDLES_DIR / f"{self.symbol}_{tf}.json"

    def _load_history(self):
        """Load persisted candle history from disk."""
        for tf in TIMEFRAMES:
            fpath = self._candle_file(tf)
            if fpath.exists():
                try:
                    data = json.loads(fpath.read_text())
                    for d in data[-MAX_CANDLES:]:
                        self.history[tf].append(Candle.from_dict(d))
                except Exception:
                    pass

    def _save_history(self, tf: str):
        """Persist candle history for one timeframe."""
        CANDLES_DIR.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self.history[tf]]
        self._candle_file(tf).write_text(json.dumps(data))

    def _bucket_start(self, ts: float, duration: int) -> float:
        """Get the start timestamp for the bucket containing ts."""
        return (ts // duration) * duration

    def on_tick(self, price: float, size: int = 1, timestamp: float = None):
        """
        Process a raw trade tick. Updates all timeframe candles simultaneously.
        Returns list of (timeframe, completed_candle) for any candle that just closed.
        """
        ts = timestamp or time.time()
        completed = []

        for tf, duration in TIMEFRAMES.items():
            bucket = self._bucket_start(ts, duration)
            cur = self.current[tf]

            if cur is None or bucket > cur.timestamp:
                # New candle period — close previous if exists
                if cur is not None:
                    cur.complete = True
                    self.history[tf].append(cur)
                    completed.append((tf, cur))
                    # Save on completion of larger timeframes (reduce I/O)
                    if duration >= 300:  # 5m+
                        self._save_history(tf)
                # Start new candle
                self.current[tf] = Candle(price, size, bucket)
            else:
                cur.update(price, size)

        # Save 1m history every 5 completed candles
        if any(tf == "1m" for tf, _ in completed):
            if len(self.history["1m"]) % 5 == 0:
                self._save_history("1m")

        return completed

    def get_candles(self, timeframe: str, count: int = 50) -> list[Candle]:
        """Get last N completed candles for a timeframe."""
        hist = list(self.history.get(timeframe, []))
        return hist[-count:]

    def get_current(self, timeframe: str) -> Optional[Candle]:
        """Get the current (in-progress) candle for a timeframe."""
        return self.current.get(timeframe)

    def get_ohlcv_arrays(self, timeframe: str, count: int = 50):
        """
        Get OHLCV as separate lists (for pattern detection).
        Returns (opens, highs, lows, closes, volumes).
        """
        candles = self.get_candles(timeframe, count)
        if not candles:
            return [], [], [], [], []
        opens = [c.open for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]
        return opens, highs, lows, closes, volumes

    def flush_all(self):
        """Persist all timeframes to disk."""
        for tf in TIMEFRAMES:
            self._save_history(tf)
