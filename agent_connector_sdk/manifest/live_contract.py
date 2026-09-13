"""Validate a live MCP tool against its pinned contract before extraction."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.manifest.tool_schema import (
    ToolSchemaContractError,
    canonical_input_schema,
    canonical_output_schema,
    compatibility_fingerprint,
    read_field,
    schema_fingerprint,
)

__all__ = ["LiveToolContract", "validate_live_tool_contract"]


@dataclass(frozen=True)
class LiveToolContract:
    """A validated live tool identity with its deterministic fingerprints."""

    name: str
    schema_sha256: str
    compatibility_sha256: str


def _single_tool(list_tools_result: Any, tool_name: str) -> Any:
    tools = read_field(list_tools_result, "tools")
    listing = list_tools_result if tools is None else tools
    if not isinstance(listing, Iterable) or isinstance(listing, str | bytes | Mapping):
        raise ToolSchemaContractError("MCP list_tools response has no tool list")
    matches = [
        tool for tool in listing if str(read_field(tool, "name") or "") == tool_name
    ]
    if len(matches) != 1:
        state = "does not expose" if not matches else "duplicates"
        raise ToolSchemaContractError(
            f"live MCP server {state} pinned tool {tool_name!r}"
        )
    return matches[0]


def _declared_types(spec: Mapping[str, Any]) -> set[str]:
    declared = spec.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return {str(item) for item in declared if item != "null"}
    alternatives = spec.get("anyOf")
    if not isinstance(alternatives, list):
        return set()
    return {
        str(item["type"])
        for item in alternatives
        if isinstance(item, Mapping) and item.get("type") not in (None, "null")
    }


def _check_argument_types(
    schema: Mapping[str, Any], tool_name: str, required: Mapping[str, str]
) -> None:
    properties = schema.get("properties")
    for argument, expected_type in sorted(required.items()):
        spec = properties.get(argument) if isinstance(properties, Mapping) else None
        if not isinstance(spec, Mapping):
            raise ToolSchemaContractError(
                f"live MCP tool {tool_name!r} is missing pinned argument {argument!r}"
            )
        if expected_type not in _declared_types(spec):
            raise ToolSchemaContractError(
                f"live MCP tool {tool_name!r} argument {argument!r} is not "
                f"{expected_type!r}"
            )


def _check_argument_enums(
    schema: Mapping[str, Any],
    tool_name: str,
    required: Mapping[str, Collection[str]] | None,
) -> None:
    properties = schema.get("properties")
    for argument, values in _enum_items(required):
        spec = properties.get(argument) if isinstance(properties, Mapping) else None
        declared = spec.get("enum") if isinstance(spec, Mapping) else None
        if isinstance(declared, list):
            enum = {str(item) for item in declared}
        elif isinstance(spec, Mapping) and "const" in spec:
            # JSON Schema ``const`` is the canonical one-value enum emitted for
            # ``Literal["one-action"]``.
            enum = {str(spec["const"])}
        else:
            enum = set()
        missing = sorted(set(values) - enum)
        if missing:
            raise ToolSchemaContractError(
                f"live MCP tool {tool_name!r} argument {argument!r} schema "
                f"does not enumerate actions {missing!r}"
            )


def _enum_items(
    required: Mapping[str, Collection[str]] | None,
) -> list[tuple[str, Collection[str]]]:
    return sorted(required.items()) if required else []


def _contract_digests(tool: Any, tool_name: str) -> tuple[str, str]:
    compatible_input = canonical_input_schema(tool, include_presentation=False)
    if not compatible_input:
        raise ToolSchemaContractError(
            f"live MCP tool {tool_name!r} has an empty input schema"
        )
    compatible_output = canonical_output_schema(tool, include_presentation=False)
    compatible = compatibility_fingerprint(
        tool_name, compatible_input, compatible_output
    )
    exact = schema_fingerprint(
        tool_name, canonical_input_schema(tool), canonical_output_schema(tool)
    )
    return exact, compatible


def validate_live_tool_contract(
    list_tools_result: Any,
    *,
    tool_name: str,
    expected_schema_sha256: str = "",
    required_argument_types: Mapping[str, str] | None = None,
    required_argument_enums: Mapping[str, Collection[str]] | None = None,
) -> LiveToolContract:
    """Validate one live MCP tool against its pinned contract.

    ``expected_schema_sha256`` pins the compatibility fingerprint (descriptions,
    titles, examples and defaults may change without breaking it);
    ``required_argument_types`` names arguments that must exist with a type.
    ``required_argument_enums`` names values that the argument's JSON Schema
    ``enum`` must declare. Action-routed tools use it so action names are part of
    the pinned structural contract rather than prose.

    Raises:
        ToolSchemaContractError: the tool is missing, duplicated, drifted, or
            lacks a required argument.
    """
    tool = _single_tool(list_tools_result, tool_name)
    compatibility_schema = canonical_input_schema(tool, include_presentation=False)
    exact_digest, compatibility_digest = _contract_digests(tool, tool_name)
    expected = expected_schema_sha256.strip().lower()
    if expected and compatibility_digest != expected:
        raise ToolSchemaContractError(
            f"live MCP tool schema fingerprint differs for {tool_name!r}"
        )
    _check_argument_types(
        compatibility_schema, tool_name, required_argument_types or {}
    )
    _check_argument_enums(compatibility_schema, tool_name, required_argument_enums)
    return LiveToolContract(
        name=tool_name,
        schema_sha256=exact_digest,
        compatibility_sha256=compatibility_digest,
    )
