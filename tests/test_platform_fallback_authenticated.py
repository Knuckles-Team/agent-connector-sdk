"""A verified MCP token and host actor binding gate platform fallback."""

import threading
from unittest.mock import AsyncMock

import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from test_platform_fallback import (
    Authority,
    FixtureRecord,
    capability,
    certified_http_admission,
    request,
)

from agent_connector_sdk.adapters.platform_fallback import PlatformFallback
from agent_connector_sdk.adapters.platform_http import PlatformHttpBackend
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.identity import ActorContext, ActorType, use_actor
from agent_connector_sdk.mcp.platform_tools import (
    VerifiedScopeAuthorizer,
    register_platform_tools,
)
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


class FixtureVerifier(TokenVerifier):
    async def verify_token(self, token):
        if token not in {"fixture-allowed", "fixture-denied"}:
            return None
        return AccessToken(
            token=token,
            client_id="actor",
            scopes=["search"] if token == "fixture-allowed" else [],
            claims={"sub": "actor", "tenant_id": "tenant"},
        )


class FixtureActorBinding(Middleware):
    """A controlled host binds the identity its verifier has admitted."""

    async def on_request(self, context, call_next):
        token = get_access_token()
        if token is None:
            return await call_next(context)
        actor = ActorContext(
            actor_id=token.claims["sub"],
            actor_type=ActorType.HUMAN,
            tenant_id=token.claims["tenant_id"],
            authenticated=True,
        )
        with use_actor(actor):
            return await call_next(context)


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.4")
@pytest.mark.asyncio
async def test_verified_mcp_token_scope_gates_the_real_http_backend(
    monkeypatch, tmp_path
):
    with ScriptedHttpServer(ScriptedResponse(body=b'{"records":[]}')) as upstream:
        base = capability()
        policy = base.backends[0].model_copy(
            update={"allowed_destinations": ("127.0.0.1",)}
        )
        cap = base.model_copy(update={"backends": (policy,)})
        backend = PlatformHttpBackend(
            policy,
            HttpClientOptions(
                base_url=upstream.base_url,
                retry=RetryPolicy(max_attempts=1),
                pin_egress=True,
                allow_loopback=True,
            ),
            "/search",
            output_model=FixtureRecord,
        )
        admission = certified_http_admission(
            monkeypatch, tmp_path, {policy.backend_id: backend}
        )
        fallback = PlatformFallback(
            (cap,),
            connector_id="connector",
            authorizer=VerifiedScopeAuthorizer(Authority()),
            admission=admission,
            retry_policies={"v1": RetryPolicy(max_attempts=1)},
        )
        app = FastMCP("verified-platform", auth=FixtureVerifier())
        app.add_middleware(FixtureActorBinding())
        register_platform_tools(app, fallback)
        ready = threading.Event()
        config = uvicorn.Config(
            app.http_app(),
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
        assert ready.wait(30) and server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}/mcp"
        try:
            async with Client(endpoint, auth="fixture-denied") as client:
                denied = await client.call_tool(
                    "platform_search", {"request": request().model_dump(mode="json")}
                )
            assert denied.data["reason"] == "unauthorized"
            assert not upstream.requests
            async with Client(endpoint, auth="fixture-allowed") as client:
                allowed = await client.call_tool(
                    "platform_search", {"request": request().model_dump(mode="json")}
                )
            assert allowed.data["outcome"] == "ok"
            assert len(upstream.requests) == 1
        finally:
            server.should_exit = True
            thread.join(15)
