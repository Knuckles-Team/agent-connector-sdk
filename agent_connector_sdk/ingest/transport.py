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
from agent_connector_sdk.ingest.contract import AcceptedContract
from agent_connector_sdk.ingest.errors import IngestConflictError, IngestError

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


class EpistemicGraphIngestTransport:
    """The ingest transport over a verified epistemic-graph client.

    Implements :class:`IngestTransport` for everything the generated client
    exposes -- ``submit`` and ``source_status`` over the shared
    :class:`~agent_connector_sdk.ingest.channel.SourceIngestChannel`, and
    ``store_blob`` over the client's own ``blob`` convenience (see
    ``store_blob``).
    """

    def __init__(self, client: Any, *, tenant_id: str = "") -> None:
        self._channel = SourceIngestChannel(client)
        self._client = client
        self._tenant_id = tenant_id

    async def accepted_contract(self, connector: str) -> AcceptedContract | None:
        """The connector pack head the engine accepted, from ``ConnectorPack.Status``."""
        from epistemic_graph.connector_pack import ConnectorPackClient

        if not self._tenant_id:
            raise IngestError("a contract check needs the transport's tenant_id")
        status = await ConnectorPackClient(self._client).status(
            tenant_id=self._tenant_id, connector=connector
        )
        if status.head is None:
            return None
        return AcceptedContract(
            digest=str(status.head.pack_digest),
            revision=str(status.head.binding_revision),
        )

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
        digest = await self._client.blob.store(data)
        return cast(str, digest)
