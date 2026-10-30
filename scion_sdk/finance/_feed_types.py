"""Tick and live-bar value types for market feeds."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class Tick:
    """A single market tick (price update)."""

    symbol: str
    price: float
    volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    timestamp: str = ""

    def __post_init__(self) -> None:
        _validate_tick(self)
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


def _validate_tick(tick: Tick) -> None:
    if not all(
        math.isfinite(value) for value in (tick.price, tick.volume, tick.bid, tick.ask)
    ):
        raise ValueError("market tick values must be finite")


@dataclass
class LiveBar:
    """A live OHLCV bar being aggregated from ticks."""

    symbol: str
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: float = 0.0
    tick_count: int = 0
    bar_start: str = ""
    bar_end: str = ""

    def update(self, tick: Tick) -> None:
        """Update the bar with a new tick."""
        _validate_tick(tick)
        if self.tick_count == 0:
            self.open = tick.price
            self.bar_start = tick.timestamp

        self.high = max(self.high, tick.price)
        self.low = min(self.low, tick.price)
        self.close = tick.price
        self.volume += tick.volume
        self.tick_count += 1
        self.bar_end = tick.timestamp

    @property
    def is_empty(self) -> bool:
        return self.tick_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
        }


def _require_bar_size(bar_size: int) -> None:
    if isinstance(bar_size, bool) or not isinstance(bar_size, int) or bar_size <= 0:
        raise ValueError("bar size must be a positive integer")


def _crossed(alert: dict[str, Any], tick: Tick) -> bool:
    return bool(
        (alert["direction"] == "above" and tick.price >= alert["price"])
        or (alert["direction"] == "below" and tick.price <= alert["price"])
    )
