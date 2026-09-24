"""Errors raised by the knowledge-ingest facade."""

from __future__ import annotations

__all__ = ["IngestConflictError", "IngestError", "IngestUnavailableError"]


class IngestError(RuntimeError):
    """A change set was not committed; the message is safe to surface."""


class IngestUnavailableError(IngestError):
    """No epistemic-graph ingest channel is configured or reachable here."""


class IngestConflictError(IngestError):
    """The stream checkpoint moved concurrently and the retry budget ran out."""
