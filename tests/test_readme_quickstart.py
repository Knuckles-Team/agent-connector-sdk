"""Proves the README's Quick Start one-file connector example runs.

The server-building code here is copied verbatim from the README's
``connector.py`` listing (and the identical copy in ``docs/tutorial.md``):
if either file renames a symbol this imports, this test fails to collect.
"""

from __future__ import annotations

from typing import Literal

from starlette.testclient import TestClient

from agent_connector_sdk.mcp.server import create_mcp_server
from agent_connector_sdk.mcp.tool_surface import register_tool_surface


def register_status_tools(server) -> None:
    @server.tool
    async def demo(action: Literal["ping"] = "ping") -> dict[str, str]:
        """Return the connector's observable status."""
        return {"action": action, "connector": "demo", "status": "ok"}


def test_readme_one_file_connector_serves_health() -> None:
    args, server, middlewares = create_mcp_server(
        "demo-connector",
        version="0.1.0",
        instructions="A minimal observable connector.",
        command_args=[],
    )
    register_tool_surface(
        server, service="demo-connector", registrars=[register_status_tools]
    )
    for middleware in middlewares:
        server.add_middleware(middleware)
    assert args.transport == "stdio"
    with TestClient(server.http_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
