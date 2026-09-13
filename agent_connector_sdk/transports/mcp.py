"""The MCP transport: sessions over streamable HTTP, stdio, or in process.

The reference :class:`~agent_connector_sdk.ports.transport.Transport`. Every
session collects the server's change notifications and can open a
``subscriptions/listen`` stream (see
:class:`~agent_connector_sdk.ports.change_source.ChangeSource`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import anyio
from fastmcp import Client

from agent_connector_sdk.ports.session import McpSession, TransportEndpoint
from agent_connector_sdk.transports.mcp_changes import ChangeFeed
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
    feed = ChangeFeed()
    client = _client(endpoint, feed)
    async with client, _single_failures(), anyio.create_task_group() as tasks:
        yield McpClientSession(client, feed=feed, tasks=tasks)
        tasks.cancel_scope.cancel()


def _client(endpoint: TransportEndpoint, feed: ChangeFeed) -> Client[Any]:
    return Client(
        client_target(endpoint),
        timeout=endpoint.timeout_seconds,
        auth=endpoint.bearer_token or None,
        message_handler=feed.on_message,
    )


def _sole_failure(group: BaseExceptionGroup[BaseException]) -> BaseException:
    return group.exceptions[0] if len(group.exceptions) == 1 else group


@asynccontextmanager
async def _single_failures() -> AsyncIterator[None]:
    # The session's task group wraps whatever the caller's block raised; a
    # single failure is re-raised as itself, so callers see the exception
    # they caused rather than a group.
    try:
        yield
    except ExceptionGroup as group:
        raise _sole_failure(group) from None
