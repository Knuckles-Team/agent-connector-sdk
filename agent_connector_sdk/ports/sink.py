"""The ``Sink`` port: durably accepts record batches and content packs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
)

__all__ = ["Sink"]


@runtime_checkable
class Sink(Protocol):
    """The ingestion authority seen from the SDK."""

    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        """Commit a record batch; the receipt is returned only after commit."""
        ...

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        """Import a content pack keyed by its digest."""
        ...
