"""The transport knowledge ingest commits through.

``EpistemicGraphIngestTransport`` wraps the shared
:class:`~agent_connector_sdk.ingest.channel.SourceIngestChannel` and marks
checkpoint races as retryable. Media bytes are stored through the verified
client's own ``blob`` convenience, which drives the generated chunked-upload
protocol (``BlobBegin``/``BlobChunkPut``/``BlobCommit``) in one call.
"""

from __future__ import annotations

from typing import Any, Protocol, cast, runtime_checkable

from epistemic_graph.generated.source_ingestion import (
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
)

from agent_connector_sdk.ingest.channel import SourceIngestChannel
from agent_connector_sdk.ingest.errors import IngestConflictError

__all__ = ["EpistemicGraphIngestTransport", "IngestTransport"]

_CONFLICT_MARKER = "CONFLICT"


@runtime_checkable
class IngestTransport(Protocol):
    """What the ingest facade needs from epistemic-graph."""

    async def submit(self, request: SourceIngestionRequest) -> SourceIngestionReceipt:
        """Commit one request; raise ``IngestConflictError`` on a checkpoint race."""
        ...

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        """The durable checkpoint for one stream."""
        ...

    async def store_blob(self, data: bytes) -> str:
        """Store bytes content-addressed; return the digest."""
        ...


class _BlobConvenience(Protocol):
    """The one method this transport needs from a client's ``blob`` attribute."""

    async def store(self, data: bytes) -> str: ...


class _BlobCapableClient(Protocol):
    """A verified client shaped like the generated ``EpistemicGraphClient``."""

    blob: _BlobConvenience


class EpistemicGraphIngestTransport:
    """The ingest transport over a verified epistemic-graph client.

    Implements :class:`IngestTransport` for everything the generated client
    exposes -- ``submit`` and ``source_status`` over the shared
    :class:`~agent_connector_sdk.ingest.channel.SourceIngestChannel`, and
    ``store_blob`` over the client's own ``blob`` convenience (see
    ``store_blob``).
    """

    def __init__(self, client: Any) -> None:
        self._channel = SourceIngestChannel(client)
        self._client = client

    async def submit(self, request: SourceIngestionRequest) -> SourceIngestionReceipt:
        """Commit ``request``; a checkpoint race becomes ``IngestConflictError``."""
        try:
            return await self._channel.submit(request)
        except RuntimeError as exc:
            if _CONFLICT_MARKER in str(exc).upper():
                raise IngestConflictError("the stream checkpoint moved") from exc
            raise

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        """The durable checkpoint for one stream."""
        return await self._channel.source_status(connector, stream)

    async def store_blob(self, data: bytes) -> str:
        """Store ``data`` content-addressed; return its digest.

        Delegates to the verified client's ``blob.store`` convenience, which
        drives the generated chunked-upload protocol (``BlobBegin`` ->
        ``BlobChunkPut`` x N -> ``BlobCommit``) in one call and returns the
        committed manifest's stable content digest. Identical bytes always
        yield the same digest (the engine dedups on arrival).
        """
        client = cast(_BlobCapableClient, self._client)
        return await client.blob.store(data)
