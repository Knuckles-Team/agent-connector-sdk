"""The ``tool`` artifact kind: tools from ``tools/list``."""

from __future__ import annotations

from typing import Any

from epistemic_graph.generated.connector_pack import PackAnnotations, ToolSideEffects

from scion_sdk.artifacts.annotations import _annotations_from_mcp
from scion_sdk.artifacts.common import (
    canonical_json,
    json_object,
    require_kind,
)
from scion_sdk.artifacts.tool_facts import (
    ToolContractFacts,
    _tool_body,
    facts_from_declaration,
)
from scion_sdk.certify.fingerprints import tool_fingerprint
from scion_sdk.contracts import CapturedArtifact, ServerIdentity
from scion_sdk.ports.errors import MalformedArtifactError
from scion_sdk.ports.session import McpSession

__all__ = ["ToolArtifactKind"]


def _with_contract_facts(
    annotations: PackAnnotations, facts: ToolContractFacts
) -> PackAnnotations:
    """Fill ``side_effects`` and ``schema_tokens`` unless the connector declared them."""
    update: dict[str, Any] = {}
    if annotations.side_effects is None:
        effects = sorted(facts.side_effects)
        update["side_effects"] = ToolSideEffects(effects[0] if effects else "none")
    if annotations.schema_tokens is None:
        update["schema_tokens"] = facts.schema_tokens
    return annotations.model_copy(update=update) if update else annotations


def _tool_entry(tool: Any, server: ServerIdentity) -> CapturedArtifact:
    body = _tool_body(tool)
    facts = facts_from_declaration(tool)
    name = body["name"]
    return CapturedArtifact(
        kind=ToolArtifactKind.kind,
        uri=f"tool://{server.name}/{name}",
        name=name,
        media_type="application/json",
        body=canonical_json(body),
        server=server,
        annotations=_with_contract_facts(
            _annotations_from_mcp(
                tool,
                tool_annotations=getattr(tool, "annotations", None),
                sdk_contract_pin=tool_fingerprint(tool),
            ),
            facts,
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
