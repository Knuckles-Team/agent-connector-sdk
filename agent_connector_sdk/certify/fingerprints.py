"""Fingerprints of client-visible MCP tool definitions.

A pin is computed from the tool definition a client receives from ``tools/list``:
an ``mcp.types.Tool`` (or its wire mapping) carrying ``inputSchema``. A
server-side ``fastmcp.tools.Tool`` keeps its schema under ``parameters``, so
reading it as a client tool yields an empty schema; that is how every fleet pin
came to be the fingerprint of ``{}``. The client-visible input schema of any MCP
tool is at least ``{"type": "object"}``, so certification refuses an empty
canonical schema outright.

The pin is the SDK's compatibility fingerprint
(:data:`~agent_connector_sdk.manifest.tool_schema.COMPATIBILITY_FINGERPRINT_ALGORITHM`)
of the tool name and canonical input schema: object keys sorted, the
presentation keys ``title``, ``description``, ``examples`` and ``$comment`` and
the runtime key ``default`` removed, string lists such as ``required`` and
``enum`` sorted, serialized compactly. The extraction adapter verifies pins with
the same function, so a certified pin is exactly what a sync run checks. The
output schema is outside that algorithm; :func:`output_schema_digest` reports it
separately.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent_connector_sdk.manifest.tool_schema import (
    ToolSchemaContractError,
    canonical_input_schema,
    compatibility_fingerprint,
    read_field,
)

__all__ = [
    "EmptyToolSchemaError",
    "is_empty_schema_pin",
    "output_schema_digest",
    "tool_fingerprint",
    "tool_name",
]


class EmptyToolSchemaError(ToolSchemaContractError):
    """A tool definition carries no input schema, so a pin of it verifies nothing."""


def tool_name(tool: Any) -> str:
    """The name of a client-visible tool definition (``""`` when absent)."""
    return str(read_field(tool, "name") or "")


def is_empty_schema_pin(tool: str, pin: str) -> bool:
    """Whether ``pin`` is the fingerprint of an empty input schema for ``tool``."""
    return pin.strip().lower() == compatibility_fingerprint(tool, {})


def tool_fingerprint(tool: Any) -> str:
    """The compatibility fingerprint of one client-visible tool definition.

    Raises:
        EmptyToolSchemaError: the definition has no input schema (for example a
            server-side tool object rather than a ``tools/list`` entry).
        ToolSchemaContractError: the definition has no name or its input schema
            is not an object.
    """
    name = tool_name(tool)
    if not name:
        raise ToolSchemaContractError("MCP tool definition has no name")
    schema = canonical_input_schema(tool, include_presentation=False)
    if not schema:
        raise EmptyToolSchemaError(
            f"MCP tool {name!r} has an empty input schema; certify the definition "
            "a client receives from tools/list"
        )
    return compatibility_fingerprint(name, schema)


def output_schema_digest(tool: Any) -> str:
    """SHA-256 of the canonical output schema, or ``""`` when none is served."""
    raw = read_field(
        tool,
        "outputSchema",
        "output_schema",
        attr_names=("output_schema", "outputSchema"),
    )
    if raw is None:
        return ""
    canonical = canonical_input_schema({"inputSchema": raw}, include_presentation=False)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
