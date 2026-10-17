"""Errors raised through the extension ports."""

from __future__ import annotations

__all__ = [
    "MalformedArtifactError",
    "MalformedSourceDataError",
    "McpPromptRejectedError",
    "McpTransportError",
    "SourceContractError",
]


class SourceContractError(RuntimeError):
    """The live source does not satisfy its pinned contract, or was not verified."""


class MalformedSourceDataError(ValueError):
    """A source returned data that does not match the declared record shape."""


class MalformedArtifactError(ValueError):
    """An MCP-served content entry is malformed for its kind."""


class McpTransportError(RuntimeError):
    """An MCP operation failed; the message names the operation, not the payload."""


class McpPromptRejectedError(McpTransportError):
    """``prompts/get`` reached the server, which then returned a protocol error.

    Raised only for a well-formed :class:`mcp.shared.exceptions.MCPError`
    response -- the server is reachable and answered, it just rejected the
    bound arguments (for example a typed parameter refusing the `{{name}}`
    placeholder). A transport failure such as a timeout or a dropped
    connection never surfaces as this error; it stays a plain
    :class:`McpTransportError`.
    """
