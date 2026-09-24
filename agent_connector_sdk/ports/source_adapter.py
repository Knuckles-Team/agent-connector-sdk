"""The ``SourceAdapter`` port: extracts records from one source stream."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from epistemic_graph.generated.source_ingestion import SourceCheckpoint

from agent_connector_sdk.contracts import (
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.ports.describes_capabilities import DescribesCapabilities
from agent_connector_sdk.ports.session import McpSession

__all__ = ["SourceAdapter"]


@runtime_checkable
class SourceAdapter(DescribesCapabilities, Protocol):
    """Describe, verify, extract page by page, and reconcile one stream."""

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Verify the live source contract before any extraction."""
        ...

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        """Extract after EG's accepted checkpoint (``None`` is initial CAS)."""
        ...

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """Compare ``known_ids`` with the ids the source currently serves."""
        ...
