"""Per-connector exponential backoff."""

from __future__ import annotations

__all__ = ["Backoff"]


class Backoff:
    """Doubles the delay after each failure up to a maximum; resets on success."""

    def __init__(self, initial_seconds: float, maximum_seconds: float) -> None:
        if initial_seconds <= 0 or maximum_seconds < initial_seconds:
            raise ValueError("backoff needs 0 < initial <= maximum")
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
