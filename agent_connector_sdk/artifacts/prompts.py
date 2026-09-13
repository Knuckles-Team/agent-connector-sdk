"""The ``prompt`` artifact kind: prompts from ``prompts/list``."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.artifacts.common import (
    canonical_json,
    json_object,
    require_kind,
)
from agent_connector_sdk.contracts import ArtifactEntry, PackRecord, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["PromptArtifactKind"]


def _prompt_entry(prompt: Any, server: ServerIdentity) -> ArtifactEntry:
    name = str(getattr(prompt, "name", "") or "")
    arguments = [
        {
            "name": str(getattr(argument, "name", "")),
            "description": str(getattr(argument, "description", "") or ""),
            "required": bool(getattr(argument, "required", False)),
        }
        for argument in getattr(prompt, "arguments", None) or []
    ]
    body = {
        "name": name,
        "description": str(getattr(prompt, "description", "") or ""),
        "arguments": arguments,
    }
    return ArtifactEntry(
        kind=PromptArtifactKind.kind,
        uri=f"prompt://{server.name}/{name}",
        name=name,
        media_type="application/json",
        body=canonical_json(body),
        server=server,
    )


class PromptArtifactKind:
    """Prompts: name, description and argument contract."""

    kind = "prompt"

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[ArtifactEntry, ...]:
        """One entry per listed prompt."""
        return tuple(
            _prompt_entry(prompt, server) for prompt in await session.list_prompts()
        )

    def validate(self, entry: ArtifactEntry) -> None:
        """The body names this prompt and lists named arguments."""
        require_kind(entry, self.kind)
        document = json_object(entry)
        arguments = document.get("arguments")
        well_formed = isinstance(arguments, list) and all(
            isinstance(argument, dict) and argument.get("name")
            for argument in arguments
        )
        if document.get("name") != entry.name or not well_formed:
            raise MalformedArtifactError(f"{entry.uri} has a malformed prompt contract")

    def to_record(self, entry: ArtifactEntry) -> PackRecord:
        """A ``McpPrompt`` record."""
        self.validate(entry)
        return PackRecord(
            record_kind="McpPrompt",
            uri=entry.uri,
            name=entry.name,
            entry_digest=entry.digest,
            attributes={"description": json_object(entry).get("description", "")},
        )
