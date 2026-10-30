"""Shared in-memory ingest transport base for ingest tests."""

from __future__ import annotations

from epistemic_graph.generated.source_ingestion import (
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
)

from scion_sdk.testing.sinks import InMemorySink


class SinkBackedEngine:
    """Records submissions and delegates them to an in-memory sink."""

    def __init__(self) -> None:
        self.sink = InMemorySink()
        self.requests: list[SourceIngestionRequest] = []

    def _gate(self) -> None:
        """Raise here to refuse a submission after it is recorded."""

    async def submit(self, request: SourceIngestionRequest) -> SourceIngestionReceipt:
        self.requests.append(request)
        self._gate()
        return await self.sink.submit(request)

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        return await self.sink.source_status(connector, stream)
