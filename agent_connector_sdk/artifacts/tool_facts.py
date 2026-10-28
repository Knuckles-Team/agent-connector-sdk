"""Public estimates for canonical captured tool bodies.

The estimate is not a tokenizer count and does not publish pack annotations.
Callers may replace it with a measured tokenizer count where available.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_connector_sdk.artifacts.annotations import (
    _annotations_from_mcp,
    _declared_annotations,
)
from agent_connector_sdk.artifacts.common import canonical_json
from agent_connector_sdk.manifest.tool_schema import (
    ToolSchemaContractError,
    canonical_input_schema,
    read_field,
)
from agent_connector_sdk.mcp.action_dispatch import is_destructive_action
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.artifacts.readable_form import ReadableForm

__all__ = [
    "DEFAULT_SCHEMA_BYTES_PER_TOKEN",
    "SideEffect",
    "ToolContractFacts",
    "facts_from_declaration",
    "schema_tokens",
]

DEFAULT_SCHEMA_BYTES_PER_TOKEN = 4


def schema_tokens(body: str) -> int:
    """Estimate tokens from the UTF-8 bytes of a canonical tool body."""
    byte_count = len(body.encode("utf-8"))
    return (
        byte_count + DEFAULT_SCHEMA_BYTES_PER_TOKEN - 1
    ) // DEFAULT_SCHEMA_BYTES_PER_TOKEN


class SideEffect(StrEnum):
    """Closed set of tool effects used by contract facts."""

    NONE = "none"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    NETWORK = "network"


class ToolContractFacts(BaseModel):
    """Typed facts declared or inferred for a captured tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    read_only: bool
    side_effects: frozenset[SideEffect]
    arg_schema: dict[str, Any]
    schema_tokens: int = Field(ge=0)
    declared_by: Literal["connector", "mcp_hint", "default"]
    readable_form: ReadableForm | None = None

    @model_validator(mode="after")
    def _validate_effects(self) -> Self:
        if SideEffect.NONE in self.side_effects and len(self.side_effects) > 1:
            raise ValueError("none cannot be combined with another side effect")
        writes = {SideEffect.WORKSPACE_WRITE, SideEffect.EXTERNAL_WRITE}
        if self.read_only and self.side_effects.intersection(writes):
            raise ValueError("read-only tools cannot declare write effects")
        return self


def _tool_body(tool: Any) -> dict[str, Any]:
    name = str(read_field(tool, "name") or "")
    try:
        input_schema = canonical_input_schema(tool)
    except ToolSchemaContractError as exc:
        raise MalformedArtifactError(
            f"tool {name!r} has no object input schema"
        ) from exc
    output_schema = read_field(
        tool, "outputSchema", "output_schema", attr_names=("output_schema",)
    )
    return {
        "name": name,
        "description": str(read_field(tool, "description") or ""),
        "input_schema": input_schema,
        "output_schema": output_schema if isinstance(output_schema, dict) else None,
    }


def facts_from_declaration(
    tool: Any, *, operation: Mapping[str, Any] | None = None
) -> ToolContractFacts:
    """Build conservative facts from a live tool and its declared hints."""
    body = _tool_body(tool)
    annotations = read_field(tool, "annotations")
    declared = _declared_annotations(tool)
    merged = _annotations_from_mcp(tool, tool_annotations=annotations)
    hint = merged.read_only_hint
    destructive = is_destructive_action(body["name"], operation)
    source: Literal["connector", "mcp_hint", "default"] = (
        "connector"
        if declared.get("read_only_hint") is not None
        else ("mcp_hint" if hint is not None else "default")
    )
    return ToolContractFacts(
        read_only=bool(hint) and not destructive,
        side_effects=(
            frozenset()
            if hint and not destructive
            else frozenset({SideEffect.EXTERNAL_WRITE})
        ),
        arg_schema=body["input_schema"],
        schema_tokens=schema_tokens(canonical_json(body)),
        declared_by=source,
    )
