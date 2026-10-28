"""The ``tool`` artifact kind: tools from ``tools/list``."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.artifacts.annotations import _annotations_from_mcp
from agent_connector_sdk.artifacts.common import (
    canonical_json,
    json_object,
    require_kind,
)
from agent_connector_sdk.artifacts.tool_facts import _tool_body
from agent_connector_sdk.certify.fingerprints import tool_fingerprint
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["ToolArtifactKind"]


def _tool_entry(tool: Any, server: ServerIdentity) -> CapturedArtifact:
    body = _tool_body(tool)
    name = body["name"]
    return CapturedArtifact(
        kind=ToolArtifactKind.kind,
        uri=f"tool://{server.name}/{name}",
        name=name,
        media_type="application/json",
        body=canonical_json(body),
        server=server,
        annotations=_annotations_from_mcp(
            tool,
            tool_annotations=getattr(tool, "annotations", None),
            sdk_contract_pin=tool_fingerprint(tool),
        ),
    )


class ToolArtifactKind:
    """Tools with canonical input and output schemas."""

    kind = "tool"

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[CapturedArtifact, ...]:
        """One entry per listed tool."""
        return tuple(_tool_entry(tool, server) for tool in await session.list_tools())

    def validate(self, entry: CapturedArtifact) -> None:
        """The body names this tool and carries an object input schema."""
        require_kind(entry, self.kind)
        document = json_object(entry)
        schema = document.get("input_schema")
        if document.get("name") != entry.name:
            raise MalformedArtifactError(f"{entry.uri} body names a different tool")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise MalformedArtifactError(f"{entry.uri} input schema is not an object")
