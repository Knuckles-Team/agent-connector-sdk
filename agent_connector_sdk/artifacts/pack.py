"""Assemble a validated content pack from MCP-served content."""

from __future__ import annotations

from collections.abc import Sequence

from agent_connector_sdk.contracts import ArtifactEntry, ContentPack
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["build_content_pack"]


async def build_content_pack(
    session: McpSession, *, connector: str, kinds: Sequence[ArtifactKind]
) -> ContentPack:
    """Read every entry of every kind, validate each, and assemble the pack.

    The pack digest is a canonical hash over the server identity and the entry
    digests, so an unchanged server yields an unchanged digest.

    Raises:
        MalformedArtifactError: an entry is malformed or two entries share a URI.
    """
    server = await session.server_identity()
    entries: list[ArtifactEntry] = []
    for kind in kinds:
        for entry in await kind.list_entries(session, server):
            kind.validate(entry)
            entries.append(entry)
    uris = [entry.uri for entry in entries]
    if len(uris) != len(set(uris)):
        raise MalformedArtifactError("a content URI is served more than once")
    return ContentPack(connector=connector, server=server, entries=tuple(entries))
