"""The ``CheckpointStore`` port: sync state a sink has acknowledged.

The connector-sync runner resumes a stream from its committed cursor and skips
an import when the pack digest is unchanged. Both values are recorded only from
sink receipts, so the store can never be ahead of what the sink committed: the
write methods take the receipt, not a cursor or digest. Until epistemic-graph
publishes cursor and pack-digest reads (RF-ADR-009 W1) the runner keeps this
state locally; an EG-backed store implements the same port.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.contracts import (
    IngestionReceipt,
    PackImportReceipt,
    SyncCursor,
)

__all__ = ["CheckpointStore"]


@runtime_checkable
class CheckpointStore(Protocol):
    """Committed cursors and imported pack digests, per connector."""

    async def committed_cursor(self, connector: str, stream: str) -> SyncCursor | None:
        """The cursor of the last batch the sink committed for ``stream``."""
        ...

    async def record_ingestion(self, connector: str, receipt: IngestionReceipt) -> None:
        """Record the cursor a sink receipt committed."""
        ...

    async def imported_pack_digest(self, connector: str) -> str | None:
        """The digest of the last pack the sink imported."""
        ...

    async def record_pack_import(
        self, connector: str, receipt: PackImportReceipt
    ) -> None:
        """Record the pack digest a sink receipt acknowledged."""
        ...
