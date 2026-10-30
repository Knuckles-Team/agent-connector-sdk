"""Tick-to-bar aggregation."""

from __future__ import annotations

from datetime import UTC, datetime

from scion_sdk.finance._feed_types import (
    LiveBar,
    Tick,
    _require_bar_size,
    _validate_tick,
)


class TickAggregator:
    """
    Aggregates raw ticks into OHLCV bars at configurable intervals.

    Usage:
        agg = TickAggregator(bar_size=60)  # 60-second bars
        agg.on_tick(tick)
        completed_bars = agg.get_completed_bars()
    """

    def __init__(self, symbol: str, bar_size_seconds: int = 60):
        _require_bar_size(bar_size_seconds)
        self.symbol = symbol
        self.bar_size = bar_size_seconds
        self._current_bar = LiveBar(symbol=symbol)
        self._completed_bars: list[LiveBar] = []
        self._tick_count = 0
        self._bar_start_time: float | None = None

    def on_tick(self, tick: Tick) -> LiveBar | None:
        """
        Process a tick. Returns a completed bar if the current bar
        has been closed by the time boundary.
        """
        _validate_tick(tick)
        now = datetime.now(UTC).timestamp()

        if self._bar_start_time is None:
            self._bar_start_time = now

        # Check if current bar should be closed
        elapsed = now - self._bar_start_time
        completed = None

        if elapsed >= self.bar_size and not self._current_bar.is_empty:
            completed = self._current_bar
            self._completed_bars.append(completed)
            self._current_bar = LiveBar(symbol=self.symbol)
            self._bar_start_time = now

        self._current_bar.update(tick)
        self._tick_count += 1
        return completed

    @property
    def current_bar(self) -> LiveBar:
        return self._current_bar

    @property
    def completed_bars(self) -> list[LiveBar]:
        return list(self._completed_bars)

    @property
    def total_ticks(self) -> int:
        return self._tick_count
