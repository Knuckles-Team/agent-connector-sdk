"""Canonical MCP tool input schemas and their fingerprints.

Extracted from ``agent_utilities.protocols.source_connectors.tool_schema``. The
digest domain strings (``agent-utilities:mcp-tool-schema:v1`` and
``agent-utilities:mcp-tool-schema-compat:v1``) are wire constants: every
``tool_schema_sha256`` already pinned in a connector manifest was computed with
them, so they are not renamed with the package.
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
    "compatibility_fingerprint",
    "read_field",
    "schema_fingerprint",
]

#: Algorithm label written into ``tool_schema_fingerprints.json`` files.
COMPATIBILITY_FINGERPRINT_ALGORITHM = "agent-utilities:mcp-tool-schema-compat:v1"

_EXACT_DOMAIN = b"agent-utilities:mcp-tool-schema:v1\x00"
_COMPATIBILITY_DOMAIN = COMPATIBILITY_FINGERPRINT_ALGORITHM.encode("ascii") + b"\x00"
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


def _fingerprint(domain: bytes, name: str, schema: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"name": str(name), "input_schema": _jsonable(schema)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(domain + payload).hexdigest()


def schema_fingerprint(name: str, schema: Mapping[str, Any]) -> str:
    """Hash an exact tool name and input schema."""
    return _fingerprint(_EXACT_DOMAIN, name, schema)


def compatibility_fingerprint(name: str, schema: Mapping[str, Any]) -> str:
    """Hash the structural tool contract (presentation keys already removed)."""
    return _fingerprint(_COMPATIBILITY_DOMAIN, name, schema)
