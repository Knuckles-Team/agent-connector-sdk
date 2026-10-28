"""Idempotent vs. conflicting event identity across one adapter's sweep.

A repeated event id with the same payload digest is idempotent: at-least-once
provider delivery or a resumed page must not fail or re-emit it. A repeated id
with a changed digest is a version conflict, refused rather than silently
overwritten.
"""

from __future__ import annotations

from enum import StrEnum

from agent_connector_sdk.adapters.event_errors import (
    EventIdentityConflictError,
    FeedBackpressureError,
)

__all__ = ["EventIdentityOutcome", "EventIdentityTracker"]

_MAX_ENTRIES = 100_000
_MAX_BYTES = 16 * 1024 * 1024


def _require_limits(max_entries: int, max_bytes: int) -> None:
    if (
        type(max_entries) is not int
        or type(max_bytes) is not int
        or not 1 <= max_entries <= _MAX_ENTRIES
        or not 1 <= max_bytes <= _MAX_BYTES
    ):
        raise ValueError("event identity limits must be positive and bounded")


class EventIdentityOutcome(StrEnum):
    """What one (event id, payload digest) pair means against what was seen."""

    NEW = "new"
    DUPLICATE = "duplicate"


class EventIdentityTracker:
    """Track each accepted event id's payload digest for one adapter instance."""

    def __init__(
        self, *, max_entries: int = _MAX_ENTRIES, max_bytes: int = _MAX_BYTES
    ) -> None:
        _require_limits(max_entries, max_bytes)
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._digests: dict[str, str] = {}
        self._base: dict[str, str] | None = None
        self._bytes = 0
        self._base_bytes = 0
        self._base_count = 0

    def fork(self) -> EventIdentityTracker:
        """Stage a page without copying the accepted identity index."""
        self._require_root()
        candidate = EventIdentityTracker(
            max_entries=self._max_entries, max_bytes=self._max_bytes
        )
        candidate._base = self._digests
        candidate._base_bytes = self._bytes
        candidate._base_count = len(self._digests)
        return candidate

    def merge(self, candidate: EventIdentityTracker) -> None:
        """Record a validated page staged from this tracker."""
        self._require_candidate(candidate)
        self._require_capacity(len(candidate._digests), candidate._bytes)
        self._digests.update(candidate._digests)
        self._bytes += candidate._bytes

    def classify(self, event_id: str, digest: str) -> EventIdentityOutcome:
        """Classify ``event_id``, recording it as seen when it is new.

        Raises:
            EventIdentityConflictError: ``event_id`` was seen before with a
                different payload digest.
        """
        known = self._lookup(event_id)
        if known is None:
            self._remember(event_id, digest)
            return EventIdentityOutcome.NEW
        if known == digest:
            return EventIdentityOutcome.DUPLICATE
        raise EventIdentityConflictError(
            f"event {event_id!r} changed payload digest from {known} to {digest}"
        )

    def _lookup(self, event_id: str) -> str | None:
        if self._base is None:
            return self._digests.get(event_id)
        return self._digests.get(event_id, self._base.get(event_id))

    def _require_root(self) -> None:
        if self._base is not None:
            raise ValueError("cannot fork a staged identity tracker")

    def _require_candidate(self, candidate: EventIdentityTracker) -> None:
        if candidate._base is not self._digests:
            raise ValueError("event identity candidate belongs to another tracker")
        if candidate._base_count != len(self._digests):
            raise ValueError("event identity candidate is stale")

    def _remember(self, event_id: str, digest: str) -> None:
        if len(event_id) + len(digest) > self._max_bytes:
            raise FeedBackpressureError("event identity capacity exhausted")
        size = len(event_id.encode("utf-8")) + len(digest.encode("utf-8"))
        self._require_capacity(1, size)
        self._digests[event_id] = digest
        self._bytes += size

    def _require_capacity(self, count: int, size: int) -> None:
        base_count = len(self._base) if self._base is not None else 0
        if (
            base_count + len(self._digests) + count > self._max_entries
            or self._base_bytes + self._bytes + size > self._max_bytes
        ):
            raise FeedBackpressureError("event identity capacity exhausted")
