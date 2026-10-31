"""The served MCP stack binds one actor per request through one path (SCION-CONNECTOR-CONTROL-R025.1-R025.5).

Each test builds a real connector server with ``create_mcp_server`` and calls an
actor-gated tool through a real fastmcp client: in memory (the stdio-equivalent
local transport) or over streamable HTTP served by uvicorn. The gated tools
mirror tunnel-manager's per-alias host inventory.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair
from mcp.shared.exceptions import MCPError

from scion_sdk.entitlements import identity_scoped_resources, require_entitled
from scion_sdk.identity import (
    ANONYMOUS_ACTOR,
    SYSTEM_ACTOR,
    AuthenticationRequiredError,
    IdentityRequiredError,
    current_actor,
    is_anonymous,
    require_authenticated_actor,
    use_actor,
)
from scion_sdk.mcp.actor_binding import (
    PRINCIPAL_GRANTS_SETTING,
    ActorBindingMiddleware,
    request_actor,
    token_actor,
)
from scion_sdk.mcp.middleware import (
    ActorRateLimitingMiddleware,
    build_middleware,
    rate_limit_client_id,
)
from scion_sdk.mcp.server import create_mcp_server

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
        require_entitled("ssh", alias)
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


def _server(*argv: str) -> FastMCP[Any]:
    _args, mcp, middlewares = create_mcp_server(
        "fixture-hosts", version="0.0.0", command_args=list(argv)
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
    """A tokenless HTTP request to a bare server carrying the binding."""
    mcp: FastMCP[Any] = FastMCP("auth-mode")
    _register_host_tools(mcp)
    mcp.add_middleware(ActorBindingMiddleware())
    with _serving(mcp) as endpoint:
        async with Client(endpoint) as client:
            yield client


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.1")
async def test_local_transport_binds_the_system_actor() -> None:
    async with Client(_server("--transport", "stdio")) as client:
        who = await client.call_tool("whoami", {})
        assert who.data == {"actor_id": SYSTEM_ACTOR.actor_id, "anonymous": False}
        listed = await client.call_tool("list_hosts", {})
        assert listed.data == list(INVENTORY)
        assert (await client.call_tool("get_host", {"alias": "lab"})).data == "lab"
        added = await client.call_tool("add_host", {"alias": "new"})
        assert added.data == "system added new"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.2")
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
            with pytest.raises(MCPError) as denied:
                await client.call_tool("get_host", {"alias": "prod-b"})
            assert denied.value.message == "not_entitled: not entitled to ssh:prod-b"
            added = await client.call_tool("add_host", {"alias": "new"})
            assert added.data == "operator-1 added new"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.3")
async def test_unauthenticated_http_binds_the_anonymous_actor() -> None:
    async with _anonymous_http() as client:
        who = await client.call_tool("whoami", {})
        assert who.data == {"actor_id": ANONYMOUS_ACTOR.actor_id, "anonymous": True}
        assert (await client.call_tool("list_hosts", {})).data == []
        with pytest.raises(MCPError) as denied:
            await client.call_tool("get_host", {"alias": "lab"})
        assert denied.value.code == -32000
        assert denied.value.message.startswith("anonymous_caller: anonymous caller")
        assert denied.value.data == {"reason": "anonymous_caller"}
        assert "Internal error" not in denied.value.message


def _jwt_server(keys: RSAKeyPair) -> FastMCP[Any]:
    return _server(
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


def _service_principal_token(keys: RSAKeyPair) -> str:
    """A client-credentials token shaped like the IdP issues one: no tenant claim."""
    return keys.create_token(
        subject="7f1c2b9e-service-account",
        issuer=ISSUER,
        audience=AUDIENCE,
        additional_claims={
            "azp": "arbora",
            "client_id": "arbora",
            "preferred_username": "service-account-arbora",
            "realm_access": {"roles": ["offline_access", "uma_authorization"]},
        },
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.3")
@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
async def test_a_no_auth_http_server_binds_the_trusted_local_actor(host: str) -> None:
    argv = ["--transport", "streamable-http", "--auth-type", "none", "--host", host]
    if host == "0.0.0.0":
        argv += ["--allowed-hosts", "127.0.0.1:0,localhost"]
    mcp = _server(*argv)
    with _serving(mcp) as endpoint:
        async with Client(endpoint) as client:
            who = await client.call_tool("whoami", {})
            assert who.data == {"actor_id": SYSTEM_ACTOR.actor_id, "anonymous": False}
            assert (await client.call_tool("list_hosts", {})).data == list(INVENTORY)
            assert (await client.call_tool("get_host", {"alias": "lab"})).data == "lab"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.3")
def test_an_implicit_auth_mode_still_refuses_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_TYPE", raising=False)
    with pytest.raises(SystemExit):
        _server("--transport", "streamable-http")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.2")
async def test_a_jwt_server_answers_a_tokenless_request_401() -> None:
    import httpx

    keys = RSAKeyPair.generate()
    with _serving(_jwt_server(keys)) as endpoint:
        response = httpx.post(endpoint, json={})
    assert response.status_code == 401


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025")
def test_every_transport_gets_the_same_binding_stack() -> None:
    def stack(*argv: str) -> list[type]:
        return [
            type(m)
            for m in create_mcp_server("s", version="0", command_args=list(argv))[2]
        ]

    keys = RSAKeyPair.generate()
    http = (
        "--transport", "streamable-http", "--auth-type", "jwt",
        "--token-issuer", ISSUER, "--token-audience", AUDIENCE,
        "--token-public-key", keys.public_key,
    )  # fmt: skip
    none = ("--transport", "streamable-http", "--auth-type", "none")
    assert stack("--transport", "stdio") == stack(*http) == stack(*none)
    assert ActorBindingMiddleware in stack("--transport", "stdio")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.6")
def test_the_rate_limiter_runs_after_the_binding_and_keys_on_the_bound_actor() -> None:
    stack = [type(m) for m in build_middleware()]
    assert stack.index(ActorBindingMiddleware) < stack.index(
        ActorRateLimitingMiddleware
    )
    with use_actor(ANONYMOUS_ACTOR):
        assert rate_limit_client_id(None) == "anonymous"
    alice = token_actor(SimpleNamespace(client_id="c", claims={"sub": "alice"}))
    bob = token_actor(SimpleNamespace(client_id="c", claims={"sub": "bob"}))
    with use_actor(alice):
        alice_bucket = rate_limit_client_id(None)
    with use_actor(bob):
        assert rate_limit_client_id(None) not in (alice_bucket, "anonymous")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.6")
async def test_the_trusted_local_principal_is_not_throttled_on_stdio() -> None:
    async with Client(_server("--transport", "stdio")) as client:
        for _ in range(100):
            assert (await client.call_tool("whoami", {})).data["actor_id"] == "system"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.6")
async def test_the_trusted_local_principal_is_not_throttled_on_http_none() -> None:
    mcp = _server("--transport", "streamable-http", "--auth-type", "none")
    with _serving(mcp) as endpoint:
        async with Client(endpoint) as client:
            for _ in range(100):
                who = await client.call_tool("whoami", {})
                assert who.data["actor_id"] == "system"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.6")
async def test_an_untrusted_actor_keeps_its_rate_limit() -> None:
    mcp: FastMCP[Any] = FastMCP("limited")
    _register_host_tools(mcp)
    for middleware in build_middleware():
        mcp.add_middleware(middleware)
    with _serving(mcp) as endpoint:
        async with Client(endpoint) as client:
            with pytest.raises(
                MCPError, match="Rate limit exceeded for client: anonymous"
            ):
                for _ in range(100):
                    await client.call_tool("whoami", {})


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.2")
async def test_a_service_principal_is_entitled_by_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = RSAKeyPair.generate()
    token = _service_principal_token(keys)
    with _serving(_jwt_server(keys)) as endpoint:
        async with Client(endpoint, auth=token) as client:
            assert (await client.call_tool("list_hosts", {})).data == []
            with pytest.raises(MCPError) as denied:
                await client.call_tool("get_host", {"alias": "lab"})
            assert denied.value.message == "not_entitled: not entitled to ssh:lab"
            monkeypatch.setenv(PRINCIPAL_GRANTS_SETTING, "other=admin;arbora=ssh:*")
            assert (await client.call_tool("list_hosts", {})).data == list(INVENTORY)
            assert (await client.call_tool("get_host", {"alias": "lab"})).data == "lab"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.4")
async def test_a_mutation_without_authentication_is_a_typed_refusal() -> None:
    async with _anonymous_http() as client:
        with pytest.raises(MCPError) as refused:
            await client.call_tool("add_host", {"alias": "new"})
    assert refused.value.code == -32000
    assert refused.value.message.startswith("authentication_required:")
    assert refused.value.data == {"reason": AuthenticationRequiredError.reason}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.5")
def test_current_actor_resolves_system_outside_any_request() -> None:
    # Process startup / background work: nothing called use_actor, nothing raises.
    assert current_actor() is SYSTEM_ACTOR
    assert request_actor() is SYSTEM_ACTOR
    # The refusal family stays for unmet requirements, not for a missing binding.
    assert issubclass(AuthenticationRequiredError, IdentityRequiredError)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.5")
async def test_a_bare_no_auth_server_serves_without_use_actor() -> None:
    bare: FastMCP[Any] = FastMCP("bare")
    _register_host_tools(bare)
    async with Client(bare) as client:
        who = await client.call_tool("whoami", {})
        assert who.data == {"actor_id": SYSTEM_ACTOR.actor_id, "anonymous": False}
        assert (await client.call_tool("list_hosts", {})).data == list(INVENTORY)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.5")
async def test_a_bare_authenticated_server_uses_the_token_identity_and_denies() -> None:
    keys = RSAKeyPair.generate()
    bare: FastMCP[Any] = FastMCP(
        "bare",
        auth=JWTVerifier(public_key=keys.public_key, issuer=ISSUER, audience=AUDIENCE),
    )
    _register_host_tools(bare)
    token = keys.create_token(
        subject="operator-2",
        issuer=ISSUER,
        audience=AUDIENCE,
        additional_claims={"tenant_id": "tenant-1", "roles": ["ssh:lab"]},
    )
    with _serving(bare) as endpoint:
        async with Client(endpoint, auth=token) as client:
            who = await client.call_tool("whoami", {})
            assert who.data == {"actor_id": "operator-2", "anonymous": False}
            assert (await client.call_tool("list_hosts", {})).data == ["lab"]
            with pytest.raises((ToolError, MCPError), match="not entitled"):
                await client.call_tool("get_host", {"alias": "prod-a"})


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.4")
async def test_the_binding_middleware_refuses_typed_on_a_bare_server() -> None:
    bare: FastMCP[Any] = FastMCP("bare")

    @bare.tool
    def whoami() -> str:
        return current_actor().actor_id

    async with Client(bare) as client:
        assert (await client.call_tool("whoami", {})).data == SYSTEM_ACTOR.actor_id
    bare.add_middleware(ActorBindingMiddleware())
    async with Client(bare) as client:
        assert (await client.call_tool("whoami", {})).data == SYSTEM_ACTOR.actor_id


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.2")
def test_a_tenantless_token_is_in_its_issuers_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PRINCIPAL_GRANTS_SETTING, "arbora=ssh:*")
    token = SimpleNamespace(
        client_id="arbora",
        claims={"sub": "svc-1", "iss": ISSUER, "azp": "arbora"},
    )
    actor = token_actor(token)
    assert (actor.actor_id, actor.tenant_id) == ("svc-1", ISSUER)
    assert "ssh:*" in actor.roles
