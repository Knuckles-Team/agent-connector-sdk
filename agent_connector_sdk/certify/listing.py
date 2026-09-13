"""List a connector server's tools through the ``Transport`` port, bounded in time.

Certification opens a session and calls ``tools/list`` only: it never calls a
tool, so it never reaches the connector's upstream API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anyio

from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.ports.transport import Transport

__all__ = ["ToolListing", "ToolListingError", "list_server_tools"]


class ToolListingError(RuntimeError):
    """The server could not be started or reached, or did not answer ``tools/list``."""


@dataclass(frozen=True)
class ToolListing:
    """What a server reported: its identity and its client-visible tools."""

    server_name: str
    server_version: str
    tools: tuple[Any, ...]


async def _listing(transport: Transport, endpoint: TransportEndpoint) -> ToolListing:
    async with transport.session(endpoint) as session:
        identity = await session.server_identity()
        tools = await session.list_tools()
    return ToolListing(identity.name, identity.version, tuple(tools))


async def list_server_tools(
    transport: Transport, endpoint: TransportEndpoint, *, timeout_seconds: float
) -> ToolListing:
    """Open a session, list the tools and close it within ``timeout_seconds``.

    Raises:
        ToolListingError: the server did not start, answer or list its tools in
            time. Its public message never includes the underlying exception.
    """
    try:
        with anyio.fail_after(timeout_seconds):
            return await _listing(transport, endpoint)
    except Exception as exc:
        raise ToolListingError("the connector server did not list its tools") from exc
