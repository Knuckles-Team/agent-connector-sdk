"""The ``ArtifactKind`` port: one kind of MCP-served content."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from scion_sdk.contracts import CapturedArtifact, ServerIdentity
from scion_sdk.ports.session import McpSession

__all__ = ["ArtifactKind"]


@runtime_checkable
class ArtifactKind(Protocol):
    """Lists, validates and maps one kind of content (tools, skills, ...)."""

    kind: str

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[CapturedArtifact, ...]:
        """Read every entry of this kind the session serves."""
        ...

    def validate(self, entry: CapturedArtifact) -> None:
        """Raise ``MalformedArtifactError`` for a malformed entry."""
        ...
