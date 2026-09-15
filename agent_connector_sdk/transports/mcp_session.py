"""A FastMCP client presented as an :class:`~agent_connector_sdk.ports.session.McpSession`."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp_types
from anyio.abc import TaskGroup
from fastmcp import Client

from agent_connector_sdk.contracts import ServerIdentity
from agent_connector_sdk.ports.change_source import ChangeEvent
from agent_connector_sdk.transports.mcp_changes import (
    ChangeFeed,
    forward_listen_events,
)

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


@dataclass(eq=False, repr=False)
class McpClientSession:
    """An open FastMCP client exposing exactly the operations the ports need.

    Args:
        client: The connected client.
        feed: Collects the change notifications the client receives.
        tasks: The task group that runs listen streams for this session;
            without one :meth:`watch` cannot subscribe.
    """

    client: Client[Any] = field(repr=False)
    feed: ChangeFeed = field(kw_only=True, repr=False)
    tasks: TaskGroup | None = field(default=None, kw_only=True, repr=False)
    _listen: anyio.CancelScope | None = field(default=None, init=False, repr=False)

    async def watch(self, resource_uris: Sequence[str]) -> bool:
        """Open a ``subscriptions/listen`` stream, replacing an earlier one.

        The new stream is acknowledged before the earlier one is closed, so no
        event published during the switch is lost.
        """
        if self.tasks is None:
            return False
        previous = self._listen
        self._listen = await self.tasks.start(
            forward_listen_events,
            self.client.session,
            self.feed,
            tuple(resource_uris),
        )
        if previous is not None:
            previous.cancel()
        return self._listen is not None

    async def next_changes(self) -> frozenset[ChangeEvent]:
        """Wait for at least one change and return every change pending."""
        return await self.feed.next_changes()

    async def server_identity(self) -> ServerIdentity:
        """Name and version from the server's discovery metadata."""
        info = self.client.server_info
        name, version = getattr(info, "name", ""), getattr(info, "version", "")
        if not name or not version:
            raise McpTransportError("MCP server did not report a name and version")
        return ServerIdentity(name=str(name), version=str(version))

    async def list_tools(self) -> Sequence[Any]:
        """``tools/list``."""
        return await self.client.list_tools()

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """``tools/call``; a tool error is raised as :class:`McpTransportError`."""
        try:
            result = await self.client.call_tool(name, dict(arguments))
        except Exception as exc:
            raise McpTransportError(f"MCP tools/call failed for {name!r}") from exc
        return decode_tool_result(result)

    async def list_prompts(self) -> Sequence[Any]:
        """``prompts/list``."""
        return await self.client.list_prompts()

    async def get_prompt(
        self, name: str, arguments: Mapping[str, str]
    ) -> mcp_types.GetPromptResult:
        """``prompts/get``; failures name the operation without source content."""
        try:
            result = await self.client.get_prompt(name, dict(arguments))
            return mcp_types.GetPromptResult.model_validate(result)
        except Exception as exc:
            raise McpTransportError(f"MCP prompts/get failed for {name!r}") from exc

    async def list_resources(self) -> Sequence[Any]:
        """``resources/list``."""
        return await self.client.list_resources()

    async def read_resource(self, uri: str) -> str:
        """``resources/read``; raises when the resource has no text content."""
        contents = await self.client.read_resource(uri)
        texts = [getattr(block, "text", None) for block in contents]
        if not texts or not all(isinstance(text, str) for text in texts):
            raise McpTransportError(f"MCP resource {uri!r} has no text content")
        return "".join(str(text) for text in texts)
