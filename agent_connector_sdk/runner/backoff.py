"""Per-connector exponential backoff."""

from __future__ import annotations

import math

__all__ = ["Backoff"]


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _validate_backoff(initial_seconds: float, maximum_seconds: float) -> None:
    values = (initial_seconds, maximum_seconds)
    if not all(_finite_number(value) for value in values):
        raise ValueError("backoff durations must be finite numbers")
    if initial_seconds <= 0 or maximum_seconds < initial_seconds:
        raise ValueError("backoff needs 0 < initial <= maximum")


class Backoff:
    """Doubles the delay after each failure up to a maximum; resets on success."""

    def __init__(self, initial_seconds: float, maximum_seconds: float) -> None:
        _validate_backoff(initial_seconds, maximum_seconds)
        self._initial = initial_seconds
        self._maximum = maximum_seconds
        self._current = initial_seconds

    def next_delay(self) -> float:
        """The delay before the next attempt; the one after it doubles."""
        delay = self._current
        self._current = min(self._current * 2, self._maximum)
        return delay

    def reset(self) -> None:
        """Start again from the initial delay."""
        self._current = self._initial
