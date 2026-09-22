"""One provisioning pass: build the content pack and import it when it changed."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from epistemic_graph.generated.connector_pack import (
    PackImportResultImported,
    PackImportResultRejected,
)

from agent_connector_sdk.artifacts.pack import (
    CapturedConnectorPack,
    build_connector_content_pack,
    build_content_pack,
)
from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.runner.errors import SinkReceiptError

__all__ = [
    "ProvisionOutcome",
    "provision_connector_content",
    "provision_content",
]


@dataclass(frozen=True)
class ProvisionOutcome:
    """What one provisioning pass did."""

    pack_digest: str
    changed: bool
    imported: int
    resource_uris: frozenset[str]


async def provision_content(
    session: McpSession,
    *,
    connector: str,
    kinds: Sequence[ArtifactKind],
    sink: Sink,
) -> ProvisionOutcome:
    """Read the served content as a pack; import it only when its digest changed.

    EG computes and owns the pack digest after the current catalog binding is
    resolved. The outcome names the MCP resource URIs a change subscription can
    follow.

    Raises:
        SinkReceiptError: the receipt names another pack.
    """
    pack = await build_content_pack(session, connector=connector, kinds=kinds)
    return await _import_pack(pack, sink)


async def provision_connector_content(
    content: ConnectorContent, *, sink: Sink
) -> ProvisionOutcome:
    """Capture and import one explicitly composed content provider.

    Calling this once per provider preserves independent ConnectorPack heads
    and receipts even when their resources are served by one GraphOS process.
    """
    return await _import_pack(await build_connector_content_pack(content), sink)


async def _import_pack(pack: CapturedConnectorPack, sink: Sink) -> ProvisionOutcome:
    result = await sink.import_pack(pack)
    if isinstance(result, PackImportResultRejected):
        raise SinkReceiptError("ConnectorPack import was rejected")
    if isinstance(result, PackImportResultImported):
        counts = result.receipt.counts
        imported = counts.published + counts.republished + counts.revised
        return ProvisionOutcome(
            result.receipt.pack_digest, True, imported, pack.resource_uris
        )
    return ProvisionOutcome(result.pack_digest, False, 0, pack.resource_uris)
