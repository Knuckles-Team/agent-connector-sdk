"""One provisioning pass: build the content pack and import it when it changed."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_connector_sdk.artifacts.pack import build_content_pack
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.checkpoint_store import CheckpointStore
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.runner.errors import SinkReceiptError

__all__ = ["ProvisionOutcome", "provision_content"]

_RESOURCE_KINDS = frozenset({"skill", "resource"})


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
    store: CheckpointStore,
) -> ProvisionOutcome:
    """Read the served content as a pack; import it only when its digest changed.

    The digest is recorded only after the sink's receipt acknowledges exactly
    this pack, so a failed import is retried on the next pass. The outcome
    names the pack entries that are MCP resources (skills and content
    resources), the URIs a change subscription can follow.

    Raises:
        SinkReceiptError: the receipt names another pack.
    """
    pack = await build_content_pack(session, connector=connector, kinds=kinds)
    uris = frozenset(
        entry.uri for entry in pack.entries if entry.kind in _RESOURCE_KINDS
    )
    if await store.imported_pack_digest(connector) == pack.digest:
        return ProvisionOutcome(pack.digest, False, 0, uris)
    receipt = await sink.import_pack(pack)
    if receipt.pack_digest != pack.digest:
        raise SinkReceiptError("pack import receipt names a different pack")
    await store.record_pack_import(connector, receipt)
    return ProvisionOutcome(pack.digest, True, receipt.imported, uris)
