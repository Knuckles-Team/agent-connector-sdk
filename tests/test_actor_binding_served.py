"""The served MCP stack binds one actor per request, by transport (SDK-CONNECTOR-CONTROL-R025.1-R025.4).

Each test builds a real connector server with ``create_mcp_server`` and calls an
actor-gated tool through a real fastmcp client: in memory (the stdio-equivalent
local transport) or over streamable HTTP served by uvicorn. The gated tools
mirror tunnel-manager's per-alias host inventory.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import RSAKeyPair
from mcp.shared.exceptions import MCPError

from agent_connector_sdk.entitlements import identity_scoped_resources
from agent_connector_sdk.identity import (
    ANONYMOUS_ACTOR,
    SYSTEM_ACTOR,
    AuthenticationRequiredError,
    current_actor,
    is_anonymous,
    require_authenticated_actor,
)
from agent_connector_sdk.mcp.actor_binding import ActorBindingMiddleware
from agent_connector_sdk.mcp.served_security import ServedSecurityOverride
from agent_connector_sdk.mcp.server import create_mcp_server

INVENTORY = ("prod-a", "prod-b", "lab", "edge")
ISSUER = "https://idp.example.invalid/realms/demo"
AUDIENCE = "fixture-hosts"


def _register_host_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool
    def list_hosts() -> list[str]:
        """List the aliases the caller is entitled to (tunnel-manager shape)."""
        return list(identity_scoped_resources("ssh", list(INVENTORY)))

    @mcp.tool
    def get_host(alias: str) -> str:
        """Return one alias, refusing an alias the caller is not entitled to."""
        if alias not in identity_scoped_resources("ssh", [alias]):
            raise PermissionError(f"not entitled to ssh host {alias!r}")
        return alias

    @mcp.tool
    def whoami() -> dict[str, Any]:
        """The bound actor's id and whether it is the anonymous actor."""
        actor = current_actor()
        return {"actor_id": actor.actor_id, "anonymous": is_anonymous(actor)}

    @mcp.tool
    def add_host(alias: str) -> str:
        """A mutation: only an authenticated actor may add an alias."""
        actor = require_authenticated_actor()
        return f"{actor.actor_id} added {alias}"


def _server(*argv: str, override: bool = False) -> FastMCP[Any]:
    _args, mcp, middlewares = create_mcp_server(
        "fixture-hosts",
        version="0.0.0",
        command_args=list(argv),
        served_security_override=(
            ServedSecurityOverride("fixture serves HTTP without auth")
            if override
            else None
        ),
    )
    _register_host_tools(mcp)
    for middleware in middlewares:
        mcp.add_middleware(middleware)
    return mcp


@contextmanager
def _serving(mcp: FastMCP[Any]) -> Iterator[str]:
    ready = threading.Event()
    config = uvicorn.Config(
        mcp.http_app(),
        host="127.0.0.1",
        port=0,
        log_level="error",
        lifespan="on",
        callback_notify=AsyncMock(side_effect=ready.set),
        timeout_notify=1,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert ready.wait(30) and server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(10)


@asynccontextmanager
async def _anonymous_http() -> AsyncIterator[Client[Any]]:
    mcp = _server("--transport", "streamable-http", override=True)
    with _serving(mcp) as endpoint:
        async with Client(endpoint) as client:
            yield client


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025.1")
async def test_local_transport_binds_the_system_actor() -> None:
    async with Client(_server("--transport", "stdio")) as client:
        who = await client.call_tool("whoami", {})
        assert who.data == {"actor_id": SYSTEM_ACTOR.actor_id, "anonymous": False}
        listed = await client.call_tool("list_hosts", {})
        assert listed.data == list(INVENTORY)
        assert (await client.call_tool("get_host", {"alias": "lab"})).data == "lab"
        added = await client.call_tool("add_host", {"alias": "new"})
        assert added.data == "system added new"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025.2")
async def test_authenticated_http_binds_the_token_actor_with_inherited_roles() -> None:
    keys = RSAKeyPair.generate()
    mcp = _server(
        "--transport",
        "streamable-http",
        "--auth-type",
        "jwt",
        "--token-issuer",
        ISSUER,
        "--token-audience",
        AUDIENCE,
        "--token-public-key",
        keys.public_key,
    )
    token = keys.create_token(
        subject="operator-1",
        issuer=ISSUER,
        audience=AUDIENCE,
        additional_claims={
            "tenant_id": "tenant-1",
            "realm_access": {"roles": ["ssh:prod-a"]},
            "resource_access": {"hosts": {"roles": ["ssh:edge"]}},
            "groups": ["/lab", "/prod-b-operators"],
        },
    )
    with _serving(mcp) as endpoint:
        async with Client(endpoint, auth=token) as client:
            listed = await client.call_tool("list_hosts", {})
            assert listed.data == ["prod-a", "lab", "edge"]
            with pytest.raises(MCPError, match="not entitled"):
                await client.call_tool("get_host", {"alias": "prod-b"})
            added = await client.call_tool("add_host", {"alias": "new"})
            assert added.data == "operator-1 added new"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025.3")
async def test_unauthenticated_http_binds_the_anonymous_actor() -> None:
    async with _anonymous_http() as client:
        who = await client.call_tool("whoami", {})
        assert who.data == {"actor_id": ANONYMOUS_ACTOR.actor_id, "anonymous": True}
        assert (await client.call_tool("list_hosts", {})).data == []
        with pytest.raises(MCPError) as denied:
            await client.call_tool("get_host", {"alias": "lab"})
        assert denied.value.code == -32000
        assert "not entitled" in denied.value.message
        assert "Internal error" not in denied.value.message


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025.4")
async def test_a_mutation_without_authentication_is_a_typed_refusal() -> None:
    async with _anonymous_http() as client:
        with pytest.raises(MCPError) as refused:
            await client.call_tool("add_host", {"alias": "new"})
    assert refused.value.code == -32000
    assert refused.value.message.startswith("authentication_required:")
    assert refused.value.data == {"reason": AuthenticationRequiredError.reason}


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025.4")
async def test_current_actor_stays_strict_outside_the_served_binding() -> None:
    bare: FastMCP[Any] = FastMCP("bare")

    @bare.tool
    def whoami() -> str:
        return current_actor().actor_id

    async with Client(bare) as client:
        with pytest.raises(ToolError, match="an actor context is required"):
            await client.call_tool("whoami", {})
    bare.add_middleware(ActorBindingMiddleware())
    async with Client(bare) as client:
        assert (await client.call_tool("whoami", {})).data == SYSTEM_ACTOR.actor_id
