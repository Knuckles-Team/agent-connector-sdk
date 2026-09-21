"""Fail-closed write-back errors."""

from __future__ import annotations

__all__ = [
    "AuthorizationDeniedError",
    "ChangeSetExpiredError",
    "ChangeSetValidationError",
    "IdempotencyConflictError",
    "OutcomeUncertainError",
    "ReconciliationRequiredError",
    "SourceVersionConflictError",
    "WriteBackError",
]


class WriteBackError(RuntimeError):
    """Base class for governed write-back refusal."""


class ChangeSetValidationError(WriteBackError, ValueError):
    """The generated change-set projection violates the SDK boundary."""


class ChangeSetExpiredError(WriteBackError):
    """The change set expired before mutation."""


class AuthorizationDeniedError(WriteBackError, PermissionError):
    """No exact verified authorization permits the source effect."""


class SourceVersionConflictError(WriteBackError):
    """The current source version differs from the optimistic base version."""


class IdempotencyConflictError(WriteBackError):
    """An idempotency key is already bound to a different effect."""


class OutcomeUncertainError(WriteBackError):
    """The transport may have applied the effect before it disconnected."""


class ReconciliationRequiredError(WriteBackError):
    """A prior uncertain attempt must reconcile before another apply."""
