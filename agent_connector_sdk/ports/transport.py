"""The ``Transport`` port: opens MCP sessions to connectors."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from agent_connector_sdk.ports.session import McpSession, TransportEndpoint

__all__ = ["Transport"]


@runtime_checkable
class Transport(Protocol):
    """Opens MCP sessions (streamable HTTP and stdio today; A2A later)."""

    name: str

    def session(
        self, endpoint: TransportEndpoint
    ) -> AbstractAsyncContextManager[McpSession]:
        """Return an async context manager yielding an open session."""
        ...
