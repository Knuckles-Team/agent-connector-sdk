"""The ``Sink`` port: durably accepts record batches and content packs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
)

__all__ = ["Sink", "SinkReadiness"]


@dataclass(frozen=True)
class SinkReadiness:
    """Whether a sink can commit ingestion right now.

    ``reason`` is set whenever ``ready`` is ``False`` and is safe to publish
    (a health check body, a log line): implementations must never put a
    credential or other secret value in it.
    """

    ready: bool
    reason: str | None = None


@runtime_checkable
class Sink(Protocol):
    """The ingestion authority seen from the SDK."""

    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        """Commit a record batch; the receipt is returned only after commit."""
        ...

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        """Import a content pack keyed by its digest."""
        ...

    async def readiness(self) -> SinkReadiness:
        """Whether this sink can commit right now, without side effects."""
        ...
