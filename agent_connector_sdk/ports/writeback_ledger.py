"""Durable EG record boundary for governed source write-back."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    ReconciliationReceipt,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackReceipt,
    WriteBackReceiptPage,
)

__all__ = ["WriteBackLedger"]


@runtime_checkable
class WriteBackLedger(Protocol):
    """Persist and read EG-owned change sets and append-only receipts."""

    async def create(self, change_set: SourceChangeSet) -> SourceChangeSet:
        """Create or idempotently recover one canonical change set."""
        ...

    async def get(self, tenant_id: str, change_set_id: str) -> SourceChangeSet | None:
        """Read the durable canonical change set."""
        ...

    async def record_attempt(self, attempt: WriteBackAttempt) -> WriteBackReceipt:
        """Append one source-effect attempt receipt."""
        ...

    async def record_reconciliation(
        self, observation: ReconciliationObservation
    ) -> ReconciliationReceipt:
        """Append one reconciliation receipt."""
        ...

    async def receipts(
        self,
        tenant_id: str,
        change_set_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 256,
    ) -> WriteBackReceiptPage:
        """Read an ordered page of append-only receipts."""
        ...
