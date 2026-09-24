"""The ``tool`` artifact kind: tools from ``tools/list``."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.artifacts.annotations import _annotations_from_mcp
from agent_connector_sdk.artifacts.common import (
    canonical_json,
    json_object,
    require_kind,
)
from agent_connector_sdk.certify.fingerprints import tool_fingerprint
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.manifest.tool_schema import (
    ToolSchemaContractError,
    canonical_input_schema,
    canonical_output_schema,
)
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["ToolArtifactKind"]


def _canonical_schemas(tool: Any, name: str) -> tuple[dict[str, Any], Any]:
    """The tool's input and output schemas in the one canonical contract form.

    Both sections of a pack tool entry use it, so EG's section digests
    (``input_schema_digest`` / ``output_schema_digest``) are deterministic for
    a served contract: a reordered ``required`` or ``enum`` list is the same
    contract and the same digest.
    """
    try:
        return canonical_input_schema(tool), canonical_output_schema(tool)
    except ToolSchemaContractError as exc:
        raise MalformedArtifactError(
            f"tool {name!r} has a non-object input or output schema"
        ) from exc


def _tool_entry(tool: Any, server: ServerIdentity) -> CapturedArtifact:
    name = str(getattr(tool, "name", "") or "")
    input_schema, output_schema = _canonical_schemas(tool, name)
    body = {
        "name": name,
        "description": str(getattr(tool, "description", "") or ""),
        "input_schema": input_schema,
        "output_schema": output_schema,
    }
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
