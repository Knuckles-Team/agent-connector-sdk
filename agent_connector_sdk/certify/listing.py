"""List a connector server's tools through the ``Transport`` port, bounded in time.

Certification opens a session, calls ``tools/list`` and reads ``connector://resources``: it never calls a
tool, so it never reaches the connector's upstream API.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import anyio

from agent_connector_sdk.artifacts.resource_descriptor import RESOURCES_URI
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.ports.transport import Transport

__all__ = ["ToolListing", "ToolListingError", "list_server_tools"]


class ToolListingError(RuntimeError):
    """The server could not be started or reached, or did not answer ``tools/list``."""


@dataclass(frozen=True)
class ToolListing:
    """What a server reported: its identity, its tools and its declaration."""

    server_name: str
    server_version: str
    tools: tuple[Any, ...]
    resources: str = ""


async def _listing(transport: Transport, endpoint: TransportEndpoint) -> ToolListing:
    async with transport.session(endpoint) as session:
        identity = await session.server_identity()
        tools = await session.list_tools()
        resources = await session.read_resource(RESOURCES_URI)
    return ToolListing(identity.name, identity.version, tuple(tools), resources)


def _bounded_timeout(timeout_seconds: float) -> float:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    return timeout_seconds


async def list_server_tools(
    transport: Transport, endpoint: TransportEndpoint, *, timeout_seconds: float
) -> ToolListing:
    """Open a session, list the tools and close it within ``timeout_seconds``.

    Raises:
        ValueError: ``timeout_seconds`` is not finite and positive.
        ToolListingError: the server did not start, answer or list its tools in
            time. Its public message never includes the underlying exception.
    """
    timeout = _bounded_timeout(timeout_seconds)
    try:
        with anyio.fail_after(timeout):
            return await _listing(transport, endpoint)
    except Exception as exc:
        raise ToolListingError("the connector server did not list its tools") from exc
