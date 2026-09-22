"""Capture MCP content into epistemic-graph's generated ConnectorPack archive."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from epistemic_graph.connector_pack import (
    ConnectorPackArchive,
    ConnectorPackArchiveBuilder,
    ConnectorPackEntryContent,
)
from epistemic_graph.generated.connector_pack import PackEntryKind
from fastmcp import FastMCP

from agent_connector_sdk.artifacts.common import json_object
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.mcp.content import (
    ConnectorContent,
    register_connector_content,
)
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession, TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

__all__ = [
    "CapturedConnectorPack",
    "build_content_pack",
]

_RESOURCE_KINDS = {
    "ontology": PackEntryKind.ONTOLOGY,
    "shapes": PackEntryKind.SHAPES,
    "manifest": PackEntryKind.MANIFEST,
    "model-profile": PackEntryKind.MODEL_PROFILE,
    "a2a-card": PackEntryKind.A2A_CARD,
}
_KINDS = {
    "tool": PackEntryKind.TOOL,
    "skill": PackEntryKind.SKILL,
    "prompt": PackEntryKind.PROMPT,
}


@dataclass(frozen=True)
class CapturedConnectorPack:
    """SDK capture metadata around one generated, immutable pack archive."""

    connector: str
    server_package_version: str
    archive: ConnectorPackArchive
    resource_uris: frozenset[str]


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _entry_content(entry: CapturedArtifact) -> ConnectorPackEntryContent:
    kind_name = entry.kind
    uri = entry.uri
    if kind_name == "resource":
        pack_kind = _RESOURCE_KINDS.get(uri.partition("://")[0])
        if pack_kind is None:
            raise MalformedArtifactError(f"{uri} has no ConnectorPack entry kind")
    else:
        pack_kind = _KINDS.get(kind_name)
        if pack_kind is None:
            raise MalformedArtifactError(
                f"{kind_name!r} has no ConnectorPack entry kind"
            )
    body = entry.body
    input_schema = output_schema = None
    if pack_kind is PackEntryKind.TOOL:
        document = json_object(entry)
        input_schema = _canonical_json_bytes(document["input_schema"])
        if document.get("output_schema") is not None:
            output_schema = _canonical_json_bytes(document["output_schema"])
    return ConnectorPackEntryContent(
        kind=pack_kind,
        uri=uri,
        name=entry.name,
        media_type=entry.media_type,
        body=body.encode("utf-8"),
        input_schema=input_schema,
        output_schema=output_schema,
        annotations=entry.annotations,
    )


async def _capture_entries(
    session: McpSession, kinds: Sequence[ArtifactKind], server: ServerIdentity
) -> tuple[CapturedArtifact, ...]:
    entries: list[CapturedArtifact] = []
    for kind in kinds:
        for entry in await kind.list_entries(session, server):
            kind.validate(entry)
            entries.append(entry)
    return tuple(entries)


def _require_unique_uris(entries: Sequence[CapturedArtifact]) -> None:
    uris = [entry.uri for entry in entries]
    if len(uris) != len(set(uris)):
        raise MalformedArtifactError("a content URI is served more than once")


async def build_content_pack(
    session: McpSession, *, connector: str, kinds: Sequence[ArtifactKind]
) -> CapturedConnectorPack:
    """Read, validate, and archive every MCP-served entry exactly once.

    Raises:
        MalformedArtifactError: an entry is malformed or two entries share a URI.
    """
    server = await session.server_identity()
    entries = await _capture_entries(session, kinds, server)
    _require_unique_uris(entries)
    server_entry = ConnectorPackEntryContent(
        kind=PackEntryKind.MCP_SERVER,
        uri=f"mcp-server://{connector}",
        name=connector,
        media_type="application/json",
        body=_canonical_json_bytes({"name": server.name, "version": server.version}),
    )
    archive = ConnectorPackArchiveBuilder.build(
        server_entry, tuple(_entry_content(entry) for entry in entries)
    )
    return CapturedConnectorPack(
        connector=connector,
        server_package_version=server.version,
        archive=archive,
        resource_uris=frozenset(
            entry.uri for entry in entries if entry.kind in {"skill", "resource"}
        ),
    )


async def build_connector_content_pack(
    content: ConnectorContent,
) -> CapturedConnectorPack:
    """Capture one declared provider into its own generated archive.

    The temporary in-process server exercises the same MCP listings and reads
    as a remotely served connector. One invocation has exactly one connector
    identity, so composing multiple providers cannot merge their pack heads.
    """
    from agent_connector_sdk.artifacts.prompts import PromptArtifactKind
    from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
    from agent_connector_sdk.artifacts.skills import SkillArtifactKind

    server: FastMCP[object] = FastMCP(
        content.connector, version=content.package_version
    )
    register_connector_content(server, content)
    endpoint = TransportEndpoint(in_process=server)
    kinds: tuple[ArtifactKind, ...] = (
        SkillArtifactKind(),
        PromptArtifactKind(),
        ResourceArtifactKind(),
    )
    async with McpTransport().session(endpoint) as session:
        return await build_content_pack(
            session, connector=content.connector, kinds=kinds
        )
