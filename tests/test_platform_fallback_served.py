"""Served platform tools fall back across real HTTP backends and report status."""

from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP
from test_platform_fallback import (
    Authority,
    FixtureRecord,
    actor,
    capability,
    certified_http_admission,
    request,
)

from scion_sdk.adapters.platform_fallback import PlatformFallback
from scion_sdk.adapters.platform_http import PlatformHttpBackend
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.http.retry import RetryPolicy
from scion_sdk.identity import use_actor
from scion_sdk.mcp.platform_tools import register_platform_tools
from scion_sdk.mcp.tool_surface import register_tool_surface
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse

_EMPTY = ScriptedResponse(body=b'{"records":[]}')


def _served(first, second, tmp_path, monkeypatch, *, allow=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    base = capability()
    policies = tuple(
        p.model_copy(update={"allowed_destinations": ("127.0.0.1",)})
        for p in base.backends
    )
    cap = base.model_copy(update={"backends": policies})
    backends = {
        policy.backend_id: PlatformHttpBackend(
            policy,
            HttpClientOptions(
                base_url=server.base_url,
                retry=RetryPolicy(max_attempts=1),
                pin_egress=True,
                allow_loopback=True,
            ),
            "/search",
            output_model=FixtureRecord,
        )
        for policy, server in zip(policies, (first, second), strict=True)
    }
    fallback = PlatformFallback(
        (cap,),
        connector_id="connector",
        authorizer=Authority(allow),
        admission=certified_http_admission(monkeypatch, tmp_path, backends),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    server = FastMCP("demo")
    register_tool_surface(
        server,
        service="demo",
        registrars=[lambda s: register_platform_tools(s, fallback)],
        package_root=tmp_path,
    )
    return server


async def _call(server, tool, req):
    with use_actor(actor()):
        async with Client(server) as client:
            return (
                await client.call_tool(tool, {"request": req.model_dump(mode="json")})
            ).data


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.6")
@pytest.mark.asyncio
async def test_served_dispatch_fallback_and_status(tmp_path, monkeypatch):
    with (
        ScriptedHttpServer(ScriptedResponse(status=503)) as first,
        ScriptedHttpServer(_EMPTY) as second,
    ):
        server = _served(first, second, tmp_path, monkeypatch)
        result = await _call(server, "platform_search", request())
        assert result["outcome"] == "ok"
        assert result["selected_backend"] == "second"
        assert [a["backend_id"] for a in result["attempts"]] == ["first", "second"]
        status = await _call(server, "platform_status", request())
        assert status["health"] == "degraded"
        assert len(first.requests) == len(second.requests) == 1

        # Unsupported and unauthorized requests dispatch nothing.
        unsupported = await _call(
            server,
            "platform_search",
            request().model_copy(update={"platform_id": "unknown"}),
        )
        assert unsupported["reason"] == "unsupported_capability"
        assert len(first.requests) == len(second.requests) == 1

    with (
        ScriptedHttpServer(ScriptedResponse(status=503)) as first,
        ScriptedHttpServer(ScriptedResponse(status=503)) as second,
    ):
        server = _served(first, second, tmp_path / "failed", monkeypatch)
        failed = await _call(server, "platform_search", request())
        assert failed["reason"] == "chain_exhausted"
        assert len(failed["attempts"]) == 2
        assert len(first.requests) == len(second.requests) == 1

    with ScriptedHttpServer(_EMPTY) as first, ScriptedHttpServer(_EMPTY) as second:
        server = _served(first, second, tmp_path / "denied", monkeypatch, allow=False)
        denied = await _call(server, "platform_search", request())
        assert denied["reason"] == "unauthorized"
        assert not first.requests and not second.requests
