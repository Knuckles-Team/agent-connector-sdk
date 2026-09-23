"""The ``SourceAdapter`` port: extracts records from one source stream."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from epistemic_graph.generated.source_ingestion import SourceCheckpoint

from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.ports.session import McpSession

__all__ = ["DescribesCapabilities", "SourceAdapter"]


@runtime_checkable
class DescribesCapabilities(Protocol):
    """The subset of ``SourceAdapter`` needed to check its capability descriptor.

    Conformance checks that only inspect ``describe()``/``kind`` (e.g.
    ``check_capability_descriptor``) should depend on this, not the full
    ``SourceAdapter``, so a conformance-only test double never needs to also
    implement ``discover``/``extract``/``reconcile``.
    """

    kind: str

    def describe(self) -> CapabilityDescriptor:
        """Declare the adapter's capabilities; must not perform I/O."""
        ...


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
