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
from epistemic_graph.generated import METHOD_IDS
from epistemic_graph.generated.connector_pack import (
    AgentLibraryMutationContext,
    McpCatalogSnapshotBinding,
    PackHeadRef,
    PackImportResult,
    PackImportResultImported,
    PackImportResultUnchanged,
    PackProducer,
)
from epistemic_graph.generated.source_ingestion import (
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
)

from agent_connector_sdk._version import __version__
from agent_connector_sdk.artifacts.pack import CapturedConnectorPack
from agent_connector_sdk.ingest.channel import SourceIngestChannel
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


def _validate_pack_result(result: PackImportResult, expected_digest: str) -> None:
    actual: str | None
    if isinstance(result, PackImportResultImported):
        actual = result.receipt.pack_digest
    else:
        actual = result.pack_digest
    if actual is not None and actual != expected_digest:
        raise ValueError("ConnectorPack result does not bind the submitted pack")


async def _probe_commit_capabilities(client: Any) -> SinkReadiness:
    """Fail closed if the installed contract or connected engine lacks a path."""
    required = ("SourceIngest", "SourceIngestStatus", "ConnectorPack")
    missing = [method for method in required if method not in METHOD_IDS]
    if missing:
        return SinkReadiness(
            ready=False, reason=f"engine wheel lacks {', '.join(missing)}"
        )
    supports = getattr(client, "supports", None)
    if not callable(supports):
        return SinkReadiness(ready=False, reason="engine capability probe unavailable")
    try:
        for method in required:
            if await supports(method) is not True:
                return SinkReadiness(
                    ready=False, reason=f"engine does not advertise {method}"
                )
    except Exception:
        # The health response is public; do not echo a transport exception
        # that may contain connection details or credential-bearing URLs.
        return SinkReadiness(ready=False, reason="engine capability probe failed")
    return SinkReadiness(ready=True)


class EpistemicGraphSink:
    """Submits batches and packs to epistemic-graph through its Python client."""

    def __init__(
        self,
        client: Any,
        pack_import_authority: PackImportAuthorityResolver | None = None,
    ) -> None:
        resolver = _require_pack_authority(client, pack_import_authority)
        self._client = client
        self._channel = SourceIngestChannel(client)
        self._packs = ConnectorPackClient(client)
        self._pack_import_authority = resolver

    async def submit(self, batch: SourceIngestionRequest) -> SourceIngestionReceipt:
        """Commit one exact generated ``SourceIngest`` request.

        Delegates to the shared :class:`~agent_connector_sdk.ingest.channel.
        SourceIngestChannel` -- the knowledge-ingest facade uses the exact
        same channel, so the wire call and receipt-binding check live in one
        place.
        """
        return await self._channel.submit(batch)

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        """Read the sole durable checkpoint from EG's generated status method."""
        return await self._channel.source_status(connector, stream)

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
        """Require the pinned client and live EG to advertise every commit path."""
        return await _probe_commit_capabilities(self._client)
