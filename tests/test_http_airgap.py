"""The air-gap setting gates both governed HTTP client transports."""

import httpx
import pytest

from scion_sdk.http.client import (
    AirgapViolation,
    create_async_http_client,
    create_http_client,
)
from scion_sdk.http.options import HttpClientOptions


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.7")
def test_airgap_governed_client_blocks_external_before_transport(monkeypatch):
    calls = []
    transport = httpx.MockTransport(
        lambda request: calls.append(request.url.host) or httpx.Response(200)
    )
    options = HttpClientOptions(base_url="https://example.com")
    monkeypatch.setenv("AIRGAP_MODE", "true")
    with create_http_client(options, transport=transport) as client:
        with pytest.raises(AirgapViolation):
            client.get("/")
        assert client.get("https://127.0.0.1/").status_code == 200
        with pytest.raises(AirgapViolation):
            client.get("https://[::ffff:8.8.8.8]/")
        monkeypatch.setenv("AIRGAP_MODE", "broken")
        with pytest.raises(AirgapViolation):
            client.get("https://127.0.0.1/")
        monkeypatch.setenv("AIRGAP_MODE", "false")
        assert client.get("/").status_code == 200
    assert calls == ["127.0.0.1", "example.com"]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.7")
async def test_airgap_async_client_blocks_external_before_transport(monkeypatch):
    calls = []
    transport = httpx.MockTransport(
        lambda request: calls.append(request.url.host) or httpx.Response(200)
    )
    monkeypatch.setenv("AIRGAP_MODE", "true")
    async with create_async_http_client(
        HttpClientOptions(base_url="https://example.com"), transport=transport
    ) as client:
        with pytest.raises(AirgapViolation):
            await client.get("/")
        assert (await client.get("https://192.168.1.4/")).status_code == 200
    assert calls == ["192.168.1.4"]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.7")
def test_airgap_refuses_proxy_even_for_local_destination(monkeypatch):
    from scion_sdk.http.client import default_ssl_context
    from scion_sdk.tls.profile import ResolvedTLSProfile

    profile = ResolvedTLSProfile(
        name="proxy",
        source="test",
        configured=True,
        system_trust=True,
        trust_env=False,
        ssl_context=default_ssl_context(),
        proxy_url="https://example.com:443",
    )
    calls = []
    transport = httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200)
    )
    monkeypatch.setenv("AIRGAP_MODE", "true")
    with (
        create_http_client(
            HttpClientOptions(base_url="https://127.0.0.1", tls=profile),
            transport=transport,
        ) as client,
        pytest.raises(AirgapViolation),
    ):
        client.get("/")
    assert calls == []
