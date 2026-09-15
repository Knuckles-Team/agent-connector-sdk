"""The MCP session operations the ports rely on, and where a connector is reached."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx2
import mcp_types

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

    async def get_prompt(
        self, name: str, arguments: Mapping[str, str]
    ) -> mcp_types.GetPromptResult:
        """``prompts/get``; retain the complete ordered, typed MCP result."""
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
    stdio child and ``bearer_token`` for a URL carry already-resolved values:
    references are resolved at the composition root before an endpoint is
    built, and neither value appears in the endpoint's ``repr``. ``auth``
    authenticates a URL endpoint per request instead of a static bearer token,
    for example :func:`agent_connector_sdk.auth.oidc.client_credentials_auth`
    (FastMCP's HTTP transport takes ``httpx2`` auth).
    """

    url: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict, repr=False)
    in_process: object | None = None
    timeout_seconds: float = 60.0
    bearer_token: str = field(default="", repr=False)
    auth: httpx2.Auth | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        problems = _endpoint_problems(self)
        if problems:
            raise ValueError("; ".join(problems))


def _endpoint_problems(endpoint: TransportEndpoint) -> list[str]:
    chosen = [
        bool(endpoint.url),
        bool(endpoint.command),
        endpoint.in_process is not None,
    ]
    checks = (
        (sum(chosen) != 1, "exactly one of url, command or in_process must be set"),
        (endpoint.timeout_seconds <= 0, "timeout_seconds must be positive"),
        (
            bool(endpoint.bearer_token) and not endpoint.url,
            "bearer_token applies only to a url endpoint",
        ),
    )
    return [message for failed, message in checks if failed] + _auth_problems(endpoint)


def _auth_problems(endpoint: TransportEndpoint) -> list[str]:
    if endpoint.auth is None:
        return []
    if not endpoint.url:
        return ["auth applies only to a url endpoint"]
    return ["set at most one of bearer_token and auth"] if endpoint.bearer_token else []
