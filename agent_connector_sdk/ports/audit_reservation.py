"""Audit reservation taken before a governed write-back source effect."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from epistemic_graph.generated.write_back import SourceChangeSet

__all__ = ["AuditReservationPort"]


@runtime_checkable
class AuditReservationPort(Protocol):
    """Reserve an audit record before the one source mutation call is made.

    ``apply`` must call :meth:`reserve` after authorization is verified and
    before the transport's source call, so a write attempt without an
    available reservation makes zero transport calls. A reservation is keyed
    by the change set's idempotency key: reserving again for the same key
    (for example a proven-no-effect restart retry) returns the same
    reservation id rather than taking a second one.
    """

    async def reserve(self, change_set: SourceChangeSet) -> str:
        """Return a reservation id bound to ``change_set``, or fail closed."""
        ...
