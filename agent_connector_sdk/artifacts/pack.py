"""Capture MCP content into epistemic-graph's generated ConnectorPack archive."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from epistemic_graph.connector_pack import (
    ConnectorPackArchive,
    ConnectorPackArchiveBuilder,
    ConnectorPackEntryContent,
)
from epistemic_graph.generated.connector_pack import PackEntryKind

from agent_connector_sdk.artifacts.common import json_object
from agent_connector_sdk.artifacts.ontology_imports import scope_ontology_imports
from agent_connector_sdk.artifacts.resource_descriptor import (
    RESOURCES_URI,
    _check_captured_descriptor,
)
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.ingest.sources import IngestSourceDeclaration
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession, TransportEndpoint

if TYPE_CHECKING:
    from agent_connector_sdk.mcp.content import ConnectorContent

__all__ = [
    "CapturedConnectorPack",
    "build_content_pack",
]

_RESOURCE_KINDS = {
    # MCP Apps are an extension of the generic resource entry, not a new
    # generated pack enum member.
    "ui": PackEntryKind.RESOURCE,
    "ontology": PackEntryKind.ONTOLOGY,
    "shapes": PackEntryKind.SHAPES,
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


def declaration_content_schema() -> bytes:
    """The JSON Schema of the ``connector://resources`` body, from its model."""
    return _canonical_json_bytes(IngestSourceDeclaration.model_json_schema())


def _entry_content(entry: CapturedArtifact) -> ConnectorPackEntryContent:
    kind_name = entry.kind
    uri = entry.uri
    if kind_name == "resource":
        pack_kind = (
            PackEntryKind.RESOURCE
            if uri == RESOURCES_URI
            else _RESOURCE_KINDS.get(uri.partition("://")[0])
        )
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
    elif pack_kind is PackEntryKind.RESOURCE and uri == RESOURCES_URI:
        output_schema = declaration_content_schema()
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


def _validate_resource_descriptors(entries: Sequence[CapturedArtifact]) -> None:
    """Validate the served declaration before it enters a content pack."""
    from rdflib import RDF, RDFS, Graph, URIRef
    from rdflib.namespace import OWL

    resources = next((entry for entry in entries if entry.uri == RESOURCES_URI), None)
    if resources is None:
        return
    descriptors = json_object(resources).get("descriptors", [])
    if not isinstance(descriptors, list) or any(
        not isinstance(d, dict) for d in descriptors
    ):
        raise MalformedArtifactError("resource descriptors must be a list of objects")
    if not descriptors:
        return
    graph = Graph()
    try:
        for entry in entries:
            if entry.kind == "resource" and entry.uri.startswith("ontology://"):
                graph.parse(data=entry.body, format="turtle")
    except Exception as exc:
        raise MalformedArtifactError("connector ontology is malformed") from exc
    classes = frozenset(
        str(subject)
        for kind in (OWL.Class, RDFS.Class)
        for subject in graph.subjects(RDF.type, kind)
        if isinstance(subject, URIRef)
    )
    for descriptor in descriptors:
        if descriptor.get("kind", "data") == "data":
            _check_captured_descriptor(descriptor, classes)


def _scope_imports(
    entries: Sequence[CapturedArtifact],
) -> tuple[CapturedArtifact, ...]:
    ontology_uris = frozenset(
        entry.uri for entry in entries if entry.uri.startswith("ontology://")
    )
    return tuple(
        scope_ontology_imports(entry, ontology_uris)
        if entry.kind == "resource" and entry.uri in ontology_uris
        else entry
        for entry in entries
    )


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
    _validate_resource_descriptors(entries)
    entries = _scope_imports(entries)
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
    from fastmcp import FastMCP

    from agent_connector_sdk.artifacts.prompts import PromptArtifactKind
    from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
    from agent_connector_sdk.artifacts.skills import SkillArtifactKind
    from agent_connector_sdk.mcp.content import register_connector_content
    from agent_connector_sdk.transports.mcp import McpTransport

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
