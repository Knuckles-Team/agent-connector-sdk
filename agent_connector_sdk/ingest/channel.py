"""The one generated ``SourceIngest`` channel.

Sends an exact generated request, checks that the receipt binds it, and reads
the durable ``SourceIngestStatus``. The bundled epistemic-graph sink and the
knowledge-ingest transport both use it.
"""

from __future__ import annotations

from typing import Any

from epistemic_graph.generated.ingestion import (
    SourceIngestStatusRequest,
    send_source_ingest,
    send_source_ingest_status,
)
from epistemic_graph.generated.source_ingestion import (
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
)

__all__ = ["SourceIngestChannel"]


def _validate_source_receipt(
    request: SourceIngestionRequest, receipt: SourceIngestionReceipt, digest: str
) -> None:
    if (
        receipt.batch_digest != digest
        or receipt.accepted_checkpoint != request.provider_checkpoint
        or receipt.mode != request.mode
        or receipt.content_hash != request.provider_checkpoint.content_hash
    ):
        raise ValueError("SourceIngest receipt does not bind the request")


class SourceIngestChannel:
    """Generated ``SourceIngest`` and ``SourceIngestStatus`` over one client."""

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ValueError("a SourceIngest channel requires a verified client")
        self._client = client

    async def submit(self, request: SourceIngestionRequest) -> SourceIngestionReceipt:
        """Commit one exact generated request; the receipt must bind it."""
        request = SourceIngestionRequest.model_validate(request)
        digest = request.canonical_digest()
        receipt = await send_source_ingest(
            self._client,
            {"request": request.model_dump(mode="json", exclude_none=True)},
            idempotency_key=f"source-ingest:{request.connector}:{digest}",
        )
        _validate_source_receipt(request, receipt, digest)
        return receipt

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        """Read the sole durable checkpoint; it must name the requested stream."""
        request = SourceIngestStatusRequest(connector=connector, stream=stream)
        status = await send_source_ingest_status(self._client, request)
        if status.connector != connector or status.stream != stream:
            raise ValueError("SourceIngest status does not bind the requested stream")
        return status
