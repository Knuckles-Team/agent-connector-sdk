"""The transport knowledge ingest commits through.

``EpistemicGraphIngestTransport`` wraps the shared
:class:`~agent_connector_sdk.ingest.channel.SourceIngestChannel` and marks
checkpoint races as retryable.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from epistemic_graph.generated.source_ingestion import (
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
)

from agent_connector_sdk.ingest.channel import SourceIngestChannel
from agent_connector_sdk.ingest.errors import (
    IngestConflictError,
    IngestUnavailableError,
)

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
    already exposes -- ``submit`` and ``source_status``, both over the shared
    :class:`~agent_connector_sdk.ingest.channel.SourceIngestChannel`. Media
    storage is not implemented: see ``store_blob``.
    """

    def __init__(self, client: Any) -> None:
        self._channel = SourceIngestChannel(client)

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
        """Not implemented against the current generated client.

        The generated epistemic-graph client exposes only a chunked blob
        upload protocol (``MethodBlobBegin``/``MethodBlobChunkPut``/
        ``MethodBlobCommit``), not a single-call store; this transport does
        not yet drive that sequence. A change set with no :class:`MediaAsset
        <agent_connector_sdk.ingest.model.MediaAsset>` entries never reaches
        this method.

        Raises:
            IngestUnavailableError: always, until a chunked-upload
                implementation exists over the generated blob methods.
        """
        del data
        raise IngestUnavailableError(
            "media storage is not implemented: the generated epistemic-graph "
            "client has no single-call blob store, only a chunked upload "
            "protocol this transport does not yet drive"
        )
