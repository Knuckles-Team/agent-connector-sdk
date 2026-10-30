"""SCION-CONNECTOR-CONTROL-R014.16: per-request DNS-pinned egress on HttpClientOptions."""

from __future__ import annotations

import socket

import httpx
import pytest

from scion_sdk.http import egress
from scion_sdk.http.client import create_async_http_client, create_http_client
from scion_sdk.http.egress import (
    PinnedEgressViolation,
    normalize_private_hosts,
)
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.http.retry import RetryPolicy


def _answers(*ips: str):
    return lambda host, port, *a, **k: [
        (
            socket.AF_INET6 if ":" in ip else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (ip, port or 0),
        )
        for ip in ips
    ]


@pytest.fixture
def seen() -> list[httpx.Request]:
    return []


def _client(seen, base_url="https://api.example.com", **kw):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    options = HttpClientOptions(
        base_url=base_url,
        pin_egress=True,
        verify_pinned_peer=False,
        retry=RetryPolicy(max_attempts=1),
        **kw,
    )
    return create_http_client(options, transport=httpx.MockTransport(handler))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_defaults_do_not_pin() -> None:
    options = HttpClientOptions(base_url="https://api.example.com")
    assert options.pin_egress is False
    assert options.allowed_private_hosts == ()
    assert options.verify_pinned_peer is True


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_public_host_is_pinned_with_host_and_sni_preserved(monkeypatch, seen) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34"))
    assert _client(seen).get("/v1/x").status_code == 200
    request = seen[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["Host"] == "api.example.com"
    assert request.extensions["sni_hostname"] == "api.example.com"


@pytest.mark.parametrize(
    "ip", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1"]
)
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_public_host_resolving_private_is_refused(monkeypatch, seen, ip) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers(ip))
    with pytest.raises(PinnedEgressViolation):
        _client(seen).get("/")
    assert seen == []


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_one_private_answer_among_public_refuses(monkeypatch, seen) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34", "10.0.0.5"))
    with pytest.raises(PinnedEgressViolation):
        _client(seen).get("/")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_allowed_private_host_resolves_in_private_space(monkeypatch, seen) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("10.1.2.3"))
    client = _client(
        seen,
        base_url="http://graph.example",
        allowed_private_hosts=("graph.example",),
        allow_plaintext=True,
    )
    assert client.get("/").status_code == 200
    assert seen[0].url.host == "10.1.2.3"
    assert seen[0].headers["Host"] == "graph.example"


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_allowed_private_host_resolving_public_is_refused(monkeypatch, seen) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34"))
    client = _client(
        seen,
        base_url="https://graph.example",
        allowed_private_hosts=("graph.example",),
    )
    with pytest.raises(PinnedEgressViolation):
        client.get("/")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_cgnat_is_private_but_unlisted_host_is_not_allowed(monkeypatch, seen) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("100.64.0.9"))
    with pytest.raises(PinnedEgressViolation):
        _client(seen, base_url="https://other.example").get("/")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_loopback_needs_allow_loopback(seen) -> None:
    with pytest.raises(PinnedEgressViolation):
        _client(seen, base_url="http://127.0.0.1:8000", allow_plaintext=True).get("/")
    ok = _client(
        seen,
        base_url="http://127.0.0.1:8000",
        allow_plaintext=True,
        allow_loopback=True,
    )
    assert ok.get("/").status_code == 200


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_plaintext_public_egress_refused(monkeypatch, seen) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34"))
    client = _client(seen, base_url="http://api.example.com", allow_plaintext=True)
    with pytest.raises(PinnedEgressViolation):
        client.get("/")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_peer_mismatch_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34"))

    class Stream:
        def get_extra_info(self, name):
            return ("203.0.113.9", 443)

    def handler(request):
        return httpx.Response(200, extensions={"network_stream": Stream()})

    options = HttpClientOptions(base_url="https://api.example.com", pin_egress=True)
    client = create_http_client(options, transport=httpx.MockTransport(handler))
    with pytest.raises(PinnedEgressViolation):
        client.get("/")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
async def test_async_client_pins(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34"))
    seen: list[httpx.Request] = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200)

    options = HttpClientOptions(
        base_url="https://api.example.com", pin_egress=True, verify_pinned_peer=False
    )
    async with create_async_http_client(
        options, transport=httpx.MockTransport(handler)
    ) as client:
        await client.get("/")
        monkeypatch.setattr(socket, "getaddrinfo", _answers("10.0.0.5"))
        with pytest.raises(PinnedEgressViolation):
            await client.get("/")
    assert seen[0].url.host == "93.184.216.34"


@pytest.mark.parametrize(
    "bad", ["*.internal", "a/b", "user@host", "[::1]", "-x.internal", "", "hé.internal"]
)
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_allowlist_must_be_exact_hostnames(bad) -> None:
    with pytest.raises(ValueError):
        HttpClientOptions(
            base_url="https://api.example.com",
            pin_egress=True,
            allowed_private_hosts=(bad,),
        )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_allowlist_normalizes_and_requires_pin_egress() -> None:
    assert normalize_private_hosts(["Graph.Example.", "10.0.0.1"]) == {
        "graph.example",
        "10.0.0.1",
    }
    with pytest.raises(ValueError, match="require pin_egress"):
        HttpClientOptions(
            base_url="https://a.example.com", allowed_private_hosts=("a.b",)
        )
    with pytest.raises(ValueError, match="require pin_egress"):
        HttpClientOptions(base_url="https://a.example.com", allow_loopback=True)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_userinfo_and_oversize_urls_refused(monkeypatch, seen) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34"))
    client = _client(seen)
    with pytest.raises(PinnedEgressViolation):
        client.get(
            "https://u:p@api.example.com/"  # sanitizer:ignore - synthetic fixture
        )
    with pytest.raises(PinnedEgressViolation):
        client.get("/" + "a" * 9000)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.16")
def test_module_exports() -> None:
    assert "DnsPinnedEgressTransport" in egress.__all__


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.30")
@pytest.mark.parametrize("ip", ["100.64.0.1", "::ffff:100.64.0.1"])
def test_shared_addresses_refuse_at_guard_and_sync_transport(monkeypatch, seen, ip):
    assert egress.egress_ip_is_blocked(ip, allow_loopback=False)
    assert not egress.validate_base_url(
        f"https://[{ip}]/" if ":" in ip else f"https://{ip}/"
    ).allowed
    monkeypatch.setattr(socket, "getaddrinfo", _answers(ip))
    with pytest.raises(PinnedEgressViolation):
        _client(seen).get("/")
    assert seen == []


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.30")
async def test_mapped_shared_address_refuses_async_transport(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _answers("::ffff:100.64.0.1"))
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200)

    options = HttpClientOptions(
        base_url="https://api.example.com", pin_egress=True, verify_pinned_peer=False
    )
    async with create_async_http_client(
        options, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(PinnedEgressViolation):
            await client.get("/")
    assert seen == []


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.30")
def test_explicit_private_host_still_allows_shared_space(monkeypatch, seen):
    monkeypatch.setattr(socket, "getaddrinfo", _answers("100.64.0.9"))
    client = _client(seen, allowed_private_hosts=("api.example.com",))
    assert client.get("/").status_code == 200
    assert seen[0].url.host == "100.64.0.9"
    assert not egress.egress_ip_is_blocked("::ffff:8.8.8.8", allow_loopback=False)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.31")
async def test_async_pinned_dns_is_cancellable_without_transport(monkeypatch):
    import asyncio
    import threading

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    seen = []
    original_resolve = egress._resolve_pinned_request

    def resolve(host, port, *args, **kwargs):
        if host == "api.example.com":
            started.set()
            release.wait(timeout=2)
        return _answers("93.184.216.34")(host, port, *args, **kwargs)

    def track_resolution(request, **kwargs):
        host = request.url.host
        result = original_resolve(request, **kwargs)
        if host == "api.example.com":
            finished.set()
        return result

    async def handler(request):
        seen.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(egress, "_resolve_pinned_request", track_resolution)
    options = HttpClientOptions(
        base_url="https://api.example.com", pin_egress=True, verify_pinned_peer=False
    )
    try:
        async with create_async_http_client(
            options, transport=httpx.MockTransport(handler)
        ) as client:
            original_request = client.build_request("GET", "/")
            task = asyncio.create_task(client.send(original_request))
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=0.5)
            assert seen == []
            release.set()
            assert await asyncio.to_thread(finished.wait, 1)
            assert original_request.url.host == "api.example.com"
            assert (await client.get("https://other.example/")).status_code == 200
    finally:
        release.set()


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.31")
async def test_async_pinning_preserves_request_body_and_authority(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _answers("93.184.216.34"))
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200)

    options = HttpClientOptions(
        base_url="https://api.example.com", pin_egress=True, verify_pinned_peer=False
    )
    async with create_async_http_client(
        options, transport=httpx.MockTransport(handler)
    ) as client:
        assert (await client.post("/items", content=b"payload")).status_code == 200
    assert seen[0].content == b"payload"
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "api.example.com"
    assert seen[0].extensions["sni_hostname"] == "api.example.com"
