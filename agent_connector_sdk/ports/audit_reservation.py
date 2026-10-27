"""Audit reservation taken before a governed write-back source effect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from epistemic_graph.generated.write_back import SourceChangeSet

__all__ = ["AuditReservation", "AuditReservationPort"]


@dataclass(frozen=True, slots=True)
class AuditReservation:
    """Audit producer's receipt for one exact governed effect."""

    reservation_id: str
    effect_key: str
    change_set_digest: str


@runtime_checkable
class AuditReservationPort(Protocol):
    """Reserve an audit record before the one source mutation call is made.

    ``apply`` must call :meth:`reserve` after authorization is verified and
    before the transport's source call, so a write attempt without an
    available reservation makes zero transport calls. A reservation is keyed
    by the change set's idempotency key: reserving again for the same key
    (for example a proven-no-effect restart retry) returns the same
    reservation rather than taking a second one. The adapter must persist the
    receipt before returning and bind it to the key and canonical digest. The
    consumer checks those bindings; the adapter remains the audit authority.
    """

    async def reserve(self, change_set: SourceChangeSet) -> AuditReservation:
        """Return a durable reservation bound to ``change_set``, or fail closed."""
        ...
