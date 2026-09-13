"""The MCP transport: sessions over streamable HTTP, stdio, or in process.

The reference :class:`~agent_connector_sdk.ports.transport.Transport`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from fastmcp import Client

from agent_connector_sdk.ports.session import McpSession, TransportEndpoint
from agent_connector_sdk.transports.mcp_session import McpClientSession

__all__ = ["McpTransport", "client_target"]


def client_target(endpoint: TransportEndpoint) -> Any:
    """The FastMCP client target for an endpoint."""
    if endpoint.in_process is not None:
        return endpoint.in_process
    if endpoint.url:
        return endpoint.url
    server = {
        "command": endpoint.command,
        "args": list(endpoint.args),
        "env": dict(endpoint.env),
    }
    return {"mcpServers": {"connector": server}}


class McpTransport:
    """Opens :class:`McpClientSession` sessions to MCP servers."""

    name = "mcp"

    def session(
        self, endpoint: TransportEndpoint
    ) -> AbstractAsyncContextManager[McpSession]:
        """A context manager that connects on entry and closes on exit."""
        return _open(endpoint)


@asynccontextmanager
async def _open(endpoint: TransportEndpoint) -> AsyncIterator[McpSession]:
    client: Client[Any] = Client(
        client_target(endpoint), timeout=endpoint.timeout_seconds
    )
    async with client:
        yield McpClientSession(client)
