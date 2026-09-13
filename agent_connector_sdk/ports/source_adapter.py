"""The ``SourceAdapter`` port: extracts records from one source stream."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
    SyncCursor,
)
from agent_connector_sdk.ports.session import McpSession

__all__ = ["SourceAdapter"]


@runtime_checkable
class SourceAdapter(Protocol):
    """Describe, verify, extract page by page, and reconcile one stream."""

    kind: str

    def describe(self) -> CapabilityDescriptor:
        """Declare the adapter's capabilities; must not perform I/O."""
        ...

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Verify the live source contract before any extraction."""
        ...

    async def extract(
        self, session: McpSession, cursor: SyncCursor | None
    ) -> RecordPage:
        """Extract the page after ``cursor`` (``None`` starts a sweep)."""
        ...

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """Compare ``known_ids`` with the ids the source currently serves."""
        ...
