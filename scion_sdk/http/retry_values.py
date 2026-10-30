"""Validate and snapshot retry policy inputs before any request runs."""

from __future__ import annotations


def _require_retry_shape(max_attempts: int, jitter: bool) -> None:
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("retry attempts must be an integer")
    if not isinstance(jitter, bool):
        raise ValueError("retry jitter must be a boolean")


def _snapshot_set[T](value: frozenset[T]) -> frozenset[T]:
    if not isinstance(value, (set, frozenset)):
        raise ValueError("retry policy sets must be sets or frozensets")
    return frozenset(value)
