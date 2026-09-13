"""The MCP session operations the ports rely on, and where a connector is reached."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agent_connector_sdk.contracts import ServerIdentity

__all__ = ["McpSession", "TransportEndpoint"]


@runtime_checkable
class McpSession(Protocol):
    """The MCP operations extraction and provisioning need from a session."""

    async def server_identity(self) -> ServerIdentity:
        """Name and version the server reported when the session opened."""
        ...

    async def list_tools(self) -> Sequence[Any]:
        """``tools/list``."""
        ...

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """``tools/call``, returning the decoded result."""
        ...

    async def list_prompts(self) -> Sequence[Any]:
        """``prompts/list``."""
        ...

    async def list_resources(self) -> Sequence[Any]:
        """``resources/list``."""
        ...

    async def read_resource(self, uri: str) -> str:
        """``resources/read``, returning the text body."""
        ...


@dataclass(frozen=True)
class TransportEndpoint:
    """Where a connector is reached.

    Exactly one of ``url`` (streamable HTTP), ``command`` (stdio) or
    ``in_process`` (a server object in this process) must be set. ``env`` for a
    stdio child carries already-resolved values: references are resolved at the
    composition root before an endpoint is built.
    """

    url: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    in_process: object | None = None
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        chosen = [bool(self.url), bool(self.command), self.in_process is not None]
        if sum(chosen) != 1:
            raise ValueError("exactly one of url, command or in_process must be set")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
