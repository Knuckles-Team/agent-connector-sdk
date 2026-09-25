"""The source POST adapter preserves bounded fail-closed mutation semantics."""

from __future__ import annotations

import httpx
import pytest

from agent_connector_sdk.http.source_egress import SourceEgressError
from agent_connector_sdk.http.source_post import safe_post_json_async


@pytest.mark.asyncio
async def test_json_post_uses_one_call_and_returns_decoded_body() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"accepted": True})

    result = await safe_post_json_async(
        "http://127.0.0.1:8181/check",
        {"checks": [1]},
        headers={"WAY-API-KEY": "secret"},
        allowed_private_hosts={"127.0.0.1"},
        transport=httpx.MockTransport(respond),
    )
    assert result == {"accepted": True}
    assert len(seen) == 1
    assert seen[0].content == b'{"checks":[1]}'
    assert seen[0].headers["WAY-API-KEY"] == "secret"


@pytest.mark.asyncio
async def test_post_rejects_redirect_without_following_it() -> None:
    seen = 0

    def redirect(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        return httpx.Response(307, headers={"location": "http://127.0.0.1/other"})

    with pytest.raises(SourceEgressError, match="redirect"):
        await safe_post_json_async(
            "http://127.0.0.1/check",
            {},
            allowed_private_hosts={"127.0.0.1"},
            transport=httpx.MockTransport(redirect),
        )
    assert seen == 1


@pytest.mark.asyncio
async def test_post_checks_request_and_response_limits() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))
    with pytest.raises(SourceEgressError, match="body exceeded"):
        await safe_post_json_async(
            "http://127.0.0.1/check",
            {"long": "value"},
            max_request_bytes=2,
            allowed_private_hosts={"127.0.0.1"},
            transport=transport,
        )
    with pytest.raises(Exception, match=r"limit|large|bytes"):
        await safe_post_json_async(
            "http://127.0.0.1/check",
            {},
            max_bytes=2,
            allowed_private_hosts={"127.0.0.1"},
            transport=transport,
        )


@pytest.mark.asyncio
async def test_post_rejects_unapproved_private_host_and_header_override() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    with pytest.raises(SourceEgressError):
        await safe_post_json_async("http://10.0.0.1/check", {}, transport=transport)
    with pytest.raises(SourceEgressError, match="header"):
        await safe_post_json_async(
            "http://127.0.0.1/check",
            {},
            headers={"Host": "attacker"},
            allowed_private_hosts={"127.0.0.1"},
            transport=transport,
        )


@pytest.mark.asyncio
async def test_empty_success_response_preserves_legacy_shape() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(204))
    assert (
        await safe_post_json_async(
            "http://127.0.0.1/check",
            {},
            allowed_private_hosts={"127.0.0.1"},
            transport=transport,
        )
        == {}
    )
