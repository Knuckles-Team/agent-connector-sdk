"""Canonical MCP tool contracts and their fingerprints.

The v2 digest binds both the input and output schemas. Its predecessor bound
only the input schema; :func:`legacy_empty_schema_fingerprint` exists solely so
certification can identify and replace the fleet's old empty-schema pins.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from agent_connector_sdk.manifest.schema_canonical import normalize_schema, to_jsonable

__all__ = [
    "COMPATIBILITY_FINGERPRINT_ALGORITHM",
    "ToolSchemaContractError",
    "canonical_input_schema",
    "canonical_output_schema",
    "compatibility_fingerprint",
    "legacy_empty_schema_fingerprint",
    "output_schema_digest",
    "read_field",
    "schema_fingerprint",
]

#: Algorithm label written into ``tool_schema_fingerprints.json`` files.
COMPATIBILITY_FINGERPRINT_ALGORITHM = "agent-connector-sdk:mcp-tool-contract-compat:v2"

_EXACT_DOMAIN = b"agent-connector-sdk:mcp-tool-contract:v2\x00"
_COMPATIBILITY_DOMAIN = COMPATIBILITY_FINGERPRINT_ALGORITHM.encode("ascii") + b"\x00"
_LEGACY_COMPATIBILITY_DOMAIN = b"agent-utilities:mcp-tool-schema-compat:v1\x00"


class ToolSchemaContractError(RuntimeError):
    """The live MCP tool differs from the pinned connector contract."""


def read_field(value: Any, *names: str, attr_names: tuple[str, ...] = ()) -> Any:
    """Read ``names`` from a mapping, or ``attr_names`` (else ``names``) from an object.

    A wire ``Tool`` mapping uses camelCase ``inputSchema``; an MCP SDK v2 object
    exposes ``input_schema`` and keeps ``inputSchema`` only as a deprecated alias,
    so objects are read in the v2 order.
    """
    if isinstance(value, Mapping):
        return next((value[name] for name in names if name in value), None)
    return next(
        (getattr(value, name) for name in attr_names or names if hasattr(value, name)),
        None,
    )


def canonical_input_schema(
    tool: Any, *, include_presentation: bool = True
) -> dict[str, Any]:
    """Return a stable JSON-compatible input schema for one MCP tool.

    Raises:
        ToolSchemaContractError: the tool's input schema is not an object.
    """
    raw = read_field(
        tool, "inputSchema", "input_schema", attr_names=("input_schema", "inputSchema")
    )
    schema = normalize_schema(to_jsonable(raw or {}), include_presentation)
    if not isinstance(schema, dict):
        raise ToolSchemaContractError("live MCP tool input schema is not an object")
    return schema


def canonical_output_schema(
    tool: Any, *, include_presentation: bool = True
) -> dict[str, Any] | None:
    """Return a stable output schema, or ``None`` when the tool declares none.

    Raises:
        ToolSchemaContractError: the declared output schema is not an object.
    """
    raw = read_field(
        tool,
        "outputSchema",
        "output_schema",
        attr_names=("output_schema", "outputSchema"),
    )
    if raw is None:
        return None
    schema = normalize_schema(to_jsonable(raw), include_presentation)
    if not isinstance(schema, dict):
        raise ToolSchemaContractError("live MCP tool output schema is not an object")
    return schema


def _canonical_bytes(value: Any) -> bytes:
    """The one serialization every tool-contract digest hashes."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _fingerprint(
    domain: bytes,
    name: str,
    input_schema: Mapping[str, Any],
    *,
    output_schema: Mapping[str, Any] | None,
) -> str:
    payload = _canonical_bytes(
        {
            "input_schema": to_jsonable(input_schema),
            "name": str(name),
            "output_schema": to_jsonable(output_schema),
        }
    )
    return hashlib.sha256(domain + payload).hexdigest()


def output_schema_digest(tool: Any) -> str:
    """SHA-256 of the compatibility-canonical output schema (D18 output pin).

    The same canonical form :func:`compatibility_fingerprint` binds: presentation
    and runtime-default keys removed, keys and string lists sorted. ``""`` means
    the tool declares no output schema.

    Raises:
        ToolSchemaContractError: the declared output schema is not an object.
    """
    canonical = canonical_output_schema(tool, include_presentation=False)
    if canonical is None:
        return ""
    return hashlib.sha256(_canonical_bytes(canonical)).hexdigest()


def schema_fingerprint(
    name: str,
    input_schema: Mapping[str, Any],
    output_schema: Mapping[str, Any] | None = None,
) -> str:
    """Hash an exact tool name, input schema and optional output schema."""
    return _fingerprint(_EXACT_DOMAIN, name, input_schema, output_schema=output_schema)


def compatibility_fingerprint(
    name: str,
    input_schema: Mapping[str, Any],
    output_schema: Mapping[str, Any] | None = None,
) -> str:
    """Hash the structural input and output contract after canonicalization."""
    return _fingerprint(
        _COMPATIBILITY_DOMAIN, name, input_schema, output_schema=output_schema
    )


def legacy_empty_schema_fingerprint(name: str) -> str:
    """The retired input-only v1 fingerprint of ``name`` with an empty schema."""
    payload = _canonical_bytes({"name": str(name), "input_schema": {}})
    return hashlib.sha256(_LEGACY_COMPATIBILITY_DOMAIN + payload).hexdigest()
