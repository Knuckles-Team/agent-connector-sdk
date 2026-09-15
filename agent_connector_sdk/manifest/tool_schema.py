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

__all__ = [
    "COMPATIBILITY_FINGERPRINT_ALGORITHM",
    "ToolSchemaContractError",
    "canonical_input_schema",
    "canonical_output_schema",
    "compatibility_fingerprint",
    "legacy_empty_schema_fingerprint",
    "read_field",
    "schema_fingerprint",
]

#: Algorithm label written into ``tool_schema_fingerprints.json`` files.
COMPATIBILITY_FINGERPRINT_ALGORITHM = "agent-connector-sdk:mcp-tool-contract-compat:v2"

_EXACT_DOMAIN = b"agent-connector-sdk:mcp-tool-contract:v2\x00"
_COMPATIBILITY_DOMAIN = COMPATIBILITY_FINGERPRINT_ALGORITHM.encode("ascii") + b"\x00"
_LEGACY_COMPATIBILITY_DOMAIN = b"agent-utilities:mcp-tool-schema-compat:v1\x00"
_PRESENTATION_KEYS = frozenset({"$comment", "description", "examples", "title"})
_RUNTIME_CONFIGURATION_KEYS = frozenset({"default"})


class ToolSchemaContractError(RuntimeError):
    """The live MCP tool differs from the pinned connector contract."""


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


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


def _keep_key(key: str, include_presentation: bool) -> bool:
    if key in _RUNTIME_CONFIGURATION_KEYS:
        return False
    return include_presentation or key not in _PRESENTATION_KEYS


def _normalize(value: Any, include_presentation: bool) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize(value[key], include_presentation)
            for key in sorted(value)
            if _keep_key(key, include_presentation)
        }
    if not isinstance(value, list):
        return value
    items = [_normalize(item, include_presentation) for item in value]
    # JSON Schema ``required`` and ``enum`` order is not semantic.
    return sorted(items) if all(isinstance(item, str) for item in items) else items


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
    schema = _normalize(_jsonable(raw or {}), include_presentation)
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
    schema = _normalize(_jsonable(raw), include_presentation)
    if not isinstance(schema, dict):
        raise ToolSchemaContractError("live MCP tool output schema is not an object")
    return schema


def _fingerprint(
    domain: bytes,
    name: str,
    input_schema: Mapping[str, Any],
    *,
    output_schema: Mapping[str, Any] | None,
) -> str:
    payload = json.dumps(
        {
            "input_schema": _jsonable(input_schema),
            "name": str(name),
            "output_schema": _jsonable(output_schema),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(domain + payload).hexdigest()


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
    payload = json.dumps(
        {"name": str(name), "input_schema": {}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(_LEGACY_COMPATIBILITY_DOMAIN + payload).hexdigest()
