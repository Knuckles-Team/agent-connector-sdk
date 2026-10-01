"""Typed failures specific to operational event feeds (SDK-OBSERVABILITY-FEEDS-R001).

These sit beside the generic :mod:`agent_connector_sdk.ports.errors` taxonomy:
a conflicting duplicate is still malformed source data, and backpressure or an
expired retention window are still the live source failing its contract, but
callers need to distinguish them from the generic cases to log and retry
correctly.
"""

from __future__ import annotations

from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)

__all__ = [
    "EventIdentityConflictError",
    "FeedBackpressureError",
    "FeedRetentionExpiredError",
]


class EventIdentityConflictError(MalformedSourceDataError):
    """A repeated event id arrived with a changed payload digest.

    A conflict is refused rather than silently overwriting the earlier
    version: the provider must emit a new identity for a changed event.
    """


class FeedBackpressureError(SourceContractError):
    """The provider signaled rate limiting (HTTP 429) or an outage.

    ``retry_after_seconds`` is advisory and is never used to fabricate a
    completed page or to advance the checkpoint.
    """

    def __init__(
        self, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class FeedRetentionExpiredError(SourceContractError):
    """The checkpoint position fell outside the provider's retention window.

    The checkpoint cannot resume from where it left off; the stream needs an
    explicit re-baseline, which is outside this adapter's authority.
    """
