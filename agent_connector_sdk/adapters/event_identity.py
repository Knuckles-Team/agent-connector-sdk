"""Idempotent vs. conflicting event identity across one adapter's sweep.

A repeated event id with the same payload digest is idempotent: at-least-once
provider delivery or a resumed page must not fail or re-emit it. A repeated id
with a changed digest is a version conflict, refused rather than silently
overwritten.
"""

from __future__ import annotations

from enum import StrEnum

from agent_connector_sdk.adapters.event_errors import EventIdentityConflictError

__all__ = ["EventIdentityOutcome", "EventIdentityTracker"]


class EventIdentityOutcome(StrEnum):
    """What one (event id, payload digest) pair means against what was seen."""

    NEW = "new"
    DUPLICATE = "duplicate"


class EventIdentityTracker:
    """Track each accepted event id's payload digest for one adapter instance."""

    def __init__(self) -> None:
        self._digests: dict[str, str] = {}
        self._base: dict[str, str] | None = None

    def fork(self) -> EventIdentityTracker:
        """Stage a page without copying the accepted identity index."""
        candidate = EventIdentityTracker()
        candidate._base = self._digests
        return candidate

    def merge(self, candidate: EventIdentityTracker) -> None:
        """Record a validated page staged from this tracker."""
        if candidate._base is not self._digests:
            raise ValueError("event identity candidate belongs to another tracker")
        self._digests.update(candidate._digests)

    def classify(self, event_id: str, digest: str) -> EventIdentityOutcome:
        """Classify ``event_id``, recording it as seen when it is new.

        Raises:
            EventIdentityConflictError: ``event_id`` was seen before with a
                different payload digest.
        """
        known = self._lookup(event_id)
        if known is None:
            self._digests[event_id] = digest
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
