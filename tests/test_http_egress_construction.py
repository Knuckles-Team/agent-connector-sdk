"""Construction-time egress refusal and request-time DNS pinning."""

from __future__ import annotations

import socket

import httpx
import pytest

from scion_sdk.http.client import create_async_http_client, create_http_client
from scion_sdk.http.egress import PinnedEgressViolation
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.2")
@pytest.mark.parametrize("factory", (create_http_client, create_async_http_client))
@pytest.mark.parametrize("host", ("10.1.2.3", "127.0.0.1", "100.64.0.1"))
def test_pinned_private_literal_refuses_before_transport_creation(
    factory, host, monkeypatch
):
    def fail_dns(*args, **kwargs):
        raise AssertionError("construction must not resolve DNS")

    monkeypatch.setattr(socket, "getaddrinfo", fail_dns)
    options = HttpClientOptions(base_url=f"https://{host}", pin_egress=True)
    with pytest.raises(PinnedEgressViolation, match="destination was rejected"):
        factory(options)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.2")
def test_allowed_private_literal_uses_real_pinned_transport() -> None:
    with ScriptedHttpServer(ScriptedResponse(body=b"ok")) as server:
        options = HttpClientOptions(
            base_url=server.base_url,
            pin_egress=True,
            allowed_private_hosts=("127.0.0.1",),
        )
        with create_http_client(options) as client:
            response = client.get("/")
    assert response.content == b"ok"
    assert len(server.requests) == 1


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.2")
async def test_hostname_resolution_is_request_scoped_for_both_clients(monkeypatch):
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    calls = []

    def resolve(*args, **kwargs):
        calls.append(args)
        return answers

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    options = HttpClientOptions(
        base_url="https://example.com", pin_egress=True, verify_pinned_peer=False
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    with create_http_client(options, transport=transport) as client:
        assert not calls
        assert client.get("/").status_code == 200
    calls.clear()
    async with create_async_http_client(options, transport=transport) as client:
        assert not calls
        assert (await client.get("/")).status_code == 200
    assert len(calls) == 1
