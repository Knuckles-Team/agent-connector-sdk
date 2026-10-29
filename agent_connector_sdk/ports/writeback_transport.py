"""Source transport operations used by governed write-back."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
)

from agent_connector_sdk.ports.audit_reservation import AuditReservation
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot

__all__ = [
    "AuditBoundWriteBackTransport",
    "ReservableWriteBackTransport",
    "WriteBackTransport",
]


@runtime_checkable
class AuditBoundWriteBackTransport(Protocol):
    """A transport whose effect receipt must include the actual audit binding."""

    async def apply_reserved(
        self,
        change_set: SourceChangeSet,
        expected_version: str,
        reservation: AuditReservation,
    ) -> WriteBackAttempt:
        """Apply with the verified durable reservation, without reserving anew."""
        ...


@runtime_checkable
class ReservableWriteBackTransport(Protocol):
    """Optional source reservation, made only after verified write approval."""

    async def prepare_writeback(self, change_set: SourceChangeSet) -> None:
        """Reserve an exact idempotency binding without performing the effect."""
        ...


@runtime_checkable
class WriteBackTransport(Protocol):
    """One connector's source read, preview, apply and reconciliation transport."""

    async def read_current(self, change_set: SourceChangeSet) -> SourceSnapshot:
        """Read the entity's current source version and selected fields."""
        ...

    async def preview(
        self, change_set: SourceChangeSet, current: SourceSnapshot
    ) -> DryRunObservation:
        """Compute a diff without mutating the source."""
        ...

    async def prior_effect(
        self, change_set: SourceChangeSet
    ) -> WriteBackAttempt | None:
        """Return an effect already committed for the idempotency key."""
        ...

    async def apply(
        self, change_set: SourceChangeSet, expected_version: str
    ) -> WriteBackAttempt:
        """Compare-and-apply under the change set's idempotency key."""
        ...

    async def reconcile(self, change_set: SourceChangeSet) -> ReconciliationObservation:
        """Determine whether an uncertain attempt had an effect."""
        ...
