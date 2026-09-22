"""The epistemic-graph sink using generated SourceIngest and ConnectorPack."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from epistemic_graph.connector_pack import (
    ConnectorPackClient,
    ConnectorPackWriteError,
    PackWriteErrorCode,
    pack_digest,
)
from epistemic_graph.generated.connector_pack import (
    AgentLibraryMutationContext,
    McpCatalogSnapshotBinding,
    PackHeadRef,
    PackImportResult,
    PackImportResultImported,
    PackImportResultUnchanged,
    PackProducer,
)
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

from agent_connector_sdk._version import __version__
from agent_connector_sdk.artifacts.pack import CapturedConnectorPack
from agent_connector_sdk.ports.sink import SinkReadiness

__all__ = [
    "EpistemicGraphSink",
    "PackImportAuthorityResolver",
]

PackImportAuthorityResolver = Callable[
    [str], Awaitable[tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]]
]


def _require_pack_authority(
    client: object, resolver: PackImportAuthorityResolver | None
) -> PackImportAuthorityResolver:
    if client is None:
        raise ValueError("epistemic-graph sink requires a verified client")
    if resolver is None:
        raise ValueError(
            "epistemic-graph sink requires a pack import authority resolver"
        )
    return resolver


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


def _validate_pack_result(result: PackImportResult, expected_digest: str) -> None:
    actual: str | None
    if isinstance(result, PackImportResultImported):
        actual = result.receipt.pack_digest
    else:
        actual = result.pack_digest
    if actual is not None and actual != expected_digest:
        raise ValueError("ConnectorPack result does not bind the submitted pack")


class EpistemicGraphSink:
    """Submits batches and packs to epistemic-graph through its Python client."""

    def __init__(
        self,
        client: Any,
        pack_import_authority: PackImportAuthorityResolver | None = None,
    ) -> None:
        resolver = _require_pack_authority(client, pack_import_authority)
        self._client = client
        self._packs = ConnectorPackClient(client)
        self._pack_import_authority = resolver

    async def submit(self, batch: SourceIngestionRequest) -> SourceIngestionReceipt:
        """Commit one exact generated ``SourceIngest`` request."""
        request = SourceIngestionRequest.model_validate(batch)
        digest = request.canonical_digest()
        receipt = await send_source_ingest(
            self._client,
            {"request": request.model_dump(mode="json", exclude_none=True)},
            idempotency_key=f"source-ingest:{request.connector}:{digest}",
        )
        _validate_source_receipt(request, receipt, digest)
        return receipt

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        """Read the sole durable checkpoint from EG's generated status method."""
        request = SourceIngestStatusRequest(connector=connector, stream=stream)
        status = await send_source_ingest_status(self._client, request)
        if status.connector != connector or status.stream != stream:
            raise ValueError("SourceIngest status does not bind the requested stream")
        return status

    def import_pack(self, pack: CapturedConnectorPack) -> Awaitable[PackImportResult]:
        """Resolve current authority and import through the generated facade."""
        return self._import_pack(pack)

    async def _import_pack(self, pack: CapturedConnectorPack) -> PackImportResult:
        catalog, context = await self._pack_import_authority(pack.connector)
        status = await self._packs.status(
            tenant_id=context.tenant_id, connector=pack.connector
        )
        try:
            return await self._import_after_status(
                pack, catalog=catalog, context=context, status=status
            )
        except ConnectorPackWriteError as error:
            if error.code is not PackWriteErrorCode.PACK_HEAD_CONFLICT:
                raise
        status = await self._packs.status(
            tenant_id=context.tenant_id, connector=pack.connector
        )
        return await self._import_after_status(
            pack, catalog=catalog, context=context, status=status
        )

    async def _import_after_status(
        self,
        pack: CapturedConnectorPack,
        *,
        catalog: McpCatalogSnapshotBinding,
        context: AgentLibraryMutationContext,
        status: Any,
    ) -> PackImportResult:
        digest = pack_digest(
            pack.connector, catalog, pack.archive.server, pack.archive.entries
        )
        if status.head is not None and status.head.pack_digest == digest:
            return PackImportResultUnchanged(
                result="unchanged",
                pack_digest=digest,
                binding_revision=status.head.binding_revision,
            )
        result = await self._packs.import_pack(
            pack.archive,
            connector=pack.connector,
            server_package_version=pack.server_package_version,
            producer=PackProducer(name="agent-connector-sdk", version=__version__),
            catalog=catalog,
            context=context,
            expected_head=(
                None
                if status.head is None
                else PackHeadRef(
                    binding_revision=status.head.binding_revision,
                    pack_digest=status.head.pack_digest,
                )
            ),
        )
        _validate_pack_result(result, digest)
        return result

    async def readiness(self) -> SinkReadiness:
        """Both generated commit paths and their injected authorities are present."""
        return SinkReadiness(ready=True)
