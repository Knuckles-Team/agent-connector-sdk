"""A FastMCP client presented as an :class:`~agent_connector_sdk.ports.session.McpSession`."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from fastmcp import Client

from agent_connector_sdk.contracts import ServerIdentity

__all__ = ["McpClientSession", "McpTransportError", "decode_tool_result"]


class McpTransportError(RuntimeError):
    """An MCP operation failed; the message names the operation, not the payload."""


def decode_tool_result(result: Any) -> Any:
    """Decode a ``tools/call`` result: JSON text content first, then structured content."""
    texts = [
        block.text
        for block in getattr(result, "content", None) or []
        if isinstance(getattr(block, "text", None), str)
    ]
    joined = "\n".join(texts).strip()
    if not joined:
        return getattr(result, "structured_content", None)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


class McpClientSession:
    """An open FastMCP client exposing exactly the operations the ports need."""

    def __init__(self, client: Client[Any]) -> None:
        self._client = client

    async def server_identity(self) -> ServerIdentity:
        """Name and version from the server's discovery metadata."""
        info = self._client.server_info
        name, version = getattr(info, "name", ""), getattr(info, "version", "")
        if not name or not version:
            raise McpTransportError("MCP server did not report a name and version")
        return ServerIdentity(name=str(name), version=str(version))

    async def list_tools(self) -> Sequence[Any]:
        """``tools/list``."""
        return await self._client.list_tools()

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """``tools/call``; a tool error is raised as :class:`McpTransportError`."""
        try:
            result = await self._client.call_tool(name, dict(arguments))
        except Exception as exc:
            raise McpTransportError(f"MCP tools/call failed for {name!r}") from exc
        return decode_tool_result(result)

    async def list_prompts(self) -> Sequence[Any]:
        """``prompts/list``."""
        return await self._client.list_prompts()

    async def list_resources(self) -> Sequence[Any]:
        """``resources/list``."""
        return await self._client.list_resources()

    async def read_resource(self, uri: str) -> str:
        """``resources/read``; raises when the resource has no text content."""
        contents = await self._client.read_resource(uri)
        texts = [getattr(block, "text", None) for block in contents]
        if not texts or not all(isinstance(text, str) for text in texts):
            raise McpTransportError(f"MCP resource {uri!r} has no text content")
        return "".join(str(text) for text in texts)
