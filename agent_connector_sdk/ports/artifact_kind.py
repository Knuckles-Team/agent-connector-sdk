"""The ``ArtifactKind`` port: one kind of MCP-served content."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.contracts import ArtifactEntry, PackRecord, ServerIdentity
from agent_connector_sdk.ports.session import McpSession

__all__ = ["ArtifactKind"]


@runtime_checkable
class ArtifactKind(Protocol):
    """Lists, validates and maps one kind of content (tools, skills, ...)."""

    kind: str

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[ArtifactEntry, ...]:
        """Read every entry of this kind the session serves."""
        ...

    def validate(self, entry: ArtifactEntry) -> None:
        """Raise ``MalformedArtifactError`` for a malformed entry."""
        ...

    def to_record(self, entry: ArtifactEntry) -> PackRecord:
        """Map a validated entry to the record it is imported as."""
        ...
