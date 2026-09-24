"""DNS-pinned egress: one resolution per request, the connection goes to that address."""

from __future__ import annotations

import socket
import ssl
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_connector_sdk.http.client import create_async_http_client, create_http_client
from agent_connector_sdk.http.egress_policy import (
    EgressPolicy,
    Pin,
    PinnedEgressViolation,
    pin_request,
)
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.pinning import (
    AsyncPinnedEgressTransport,
    PinnedEgressTransport,
)
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.testing.certificates import issue_test_certificates
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from agent_connector_sdk.tls.profile import ResolvedTLSProfile
from agent_connector_sdk.tls.resolve import resolve_tls_profile

PUBLIC = "93.184.216.34"
UNTESTED = EgressPolicy(verify_peer=False)


def _dns(*answers: tuple[str, ...]) -> tuple[Callable[..., list[Any]], list[str]]:
    """A resolver that returns the next answer set on every call (rebinding)."""
    queue = list(answers)
    calls: list[str] = []

    def resolve(host: str, port: Any) -> list[Any]:
        calls.append(host)
        ips = queue.pop(0) if len(queue) > 1 else queue[0]
        return [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in ips]

    return resolve, calls


def _recording() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), seen


def test_rebinding_after_the_check_cannot_redirect_the_connection() -> None:
    resolver, calls = _dns((PUBLIC,), ("10.0.0.5",))
    inner, seen = _recording()
    transport = PinnedEgressTransport(inner, UNTESTED, resolver=resolver)
    with httpx.Client(transport=transport) as client:
        assert client.get("https://api.example.com/v1/x").status_code == 200
        (sent,) = seen
        assert sent.url.host == PUBLIC and sent.url.path == "/v1/x"
        assert sent.headers["host"] == "api.example.com"
        assert sent.extensions["sni_hostname"] == "api.example.com"
        assert calls == ["api.example.com"]
        with pytest.raises(PinnedEgressViolation, match="outside its boundary"):
            client.get("https://api.example.com/v1/x")
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("host", "answers", "policy"),
    [
        ("api.example.com", (PUBLIC, "10.0.0.5"), UNTESTED),
        ("api.example.com", ("169.254.169.254",), UNTESTED),
        ("api.example.com", ("127.0.0.1",), UNTESTED),
        (
            "vault.lab",
            (PUBLIC,),
            EgressPolicy.for_hosts(["Vault.Lab."], verify_peer=False),
        ),
    ],
)
def test_addresses_outside_the_boundary_are_refused(
    host: str, answers: tuple[str, ...], policy: EgressPolicy
) -> None:
    resolver, _ = _dns(answers)
    with pytest.raises(PinnedEgressViolation, match="outside its boundary"):
        pin_request(httpx.Request("GET", f"https://{host}/"), policy, resolver)


def test_allowlisted_private_hosts_and_loopback() -> None:
    policy = EgressPolicy.for_hosts(["vault.lab"], verify_peer=False)
    resolver, _ = _dns(("100.64.0.9",))
    pin = pin_request(
        httpx.Request("GET", "http://vault.lab:8200/v1"), policy, resolver
    )
    assert pin == Pin("vault.lab", "100.64.0.9", ("http", 8200))
    loopback = EgressPolicy(allow_loopback=True, verify_peer=False)
    resolver, _ = _dns(("127.0.0.1",))
    assert pin_request(httpx.Request("GET", "https://a.test/"), loopback, resolver)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/",
        "https://user:pw@api.example.com/",
        "ftp://api.example.com/",
    ],
)
def test_plaintext_public_credentials_and_schemes_are_refused(url: str) -> None:
    resolver, _ = _dns((PUBLIC,))
    with pytest.raises(PinnedEgressViolation):
        pin_request(httpx.Request("GET", url), UNTESTED, resolver)


def test_unresolvable_hosts_are_refused() -> None:
    def broken(host: str, port: Any) -> list[Any]:
        raise OSError("nxdomain")

    with pytest.raises(PinnedEgressViolation, match="DNS resolution failed"):
        pin_request(httpx.Request("GET", "https://gone.example/"), UNTESTED, broken)


def test_a_pinned_connection_never_serves_a_second_host() -> None:
    resolver, _ = _dns((PUBLIC,))
    inner, _ = _recording()
    transport = PinnedEgressTransport(inner, UNTESTED, resolver=resolver)
    with httpx.Client(transport=transport) as client:
        client.get("https://a.example.com/")
        with pytest.raises(PinnedEgressViolation, match="cross origins"):
            client.get("https://b.example.com/")


class _Stream:
    def __init__(self, peer: str) -> None:
        self._peer = peer

    def get_extra_info(self, name: str) -> Any:
        return (self._peer, 443) if name == "server_addr" else None


@pytest.mark.parametrize(
    ("extensions", "reason"),
    [({"network_stream": _Stream("10.9.9.9")}, "did not match"), ({}, "unavailable")],
)
def test_the_peer_must_be_the_pinned_address(
    extensions: dict[str, Any], reason: str
) -> None:
    resolver, _ = _dns((PUBLIC,))
    inner = httpx.MockTransport(
        lambda request: httpx.Response(200, extensions=extensions)
    )
    transport = PinnedEgressTransport(inner, EgressPolicy(), resolver=resolver)
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(PinnedEgressViolation, match=reason),
    ):
        client.get("https://api.example.com/")


@pytest.fixture
def server() -> Iterator[ScriptedHttpServer]:
    with ScriptedHttpServer() as scripted:
        yield scripted


def test_real_connection_goes_to_the_pin_and_passes_peer_verification(
    server: ScriptedHttpServer,
) -> None:
    server.enqueue(ScriptedResponse(body=b"ok"))
    port = httpx.URL(server.base_url).port
    resolver, _ = _dns(("127.0.0.1",))
    policy = EgressPolicy.for_hosts(["svc.internal"])
    transport = PinnedEgressTransport(httpx.HTTPTransport(), policy, resolver=resolver)
    with httpx.Client(transport=transport) as client:
        response = client.get(f"http://svc.internal:{port}/health")
    assert response.text == "ok"
    assert server.requests[0].headers["host"] == f"svc.internal:{port}"


def test_tls_verifies_the_logical_host_not_the_pinned_address(tmp_path: Path) -> None:
    certificates = issue_test_certificates()
    profile = resolve_tls_profile(
        "demo", profile={"ca_bundle_pem": certificates.ca_pem}
    )
    ok = ScriptedResponse(body=b"ok")
    with ScriptedHttpServer(
        ok, ssl_context=certificates.server_context(tmp_path)
    ) as server:
        port = httpx.URL(server.base_url).port
        policy = EgressPolicy.for_hosts(["localhost", "impostor.internal"])
        resolver, _ = _dns(("127.0.0.1",))
        for host, trusted in (("localhost", True), ("impostor.internal", False)):
            inner = httpx.HTTPTransport(verify=profile.ssl_context)
            transport = PinnedEgressTransport(inner, policy, resolver=resolver)
            with httpx.Client(transport=transport) as client:
                if trusted:
                    assert client.get(f"https://{host}:{port}/").text == "ok"
                    continue
                with pytest.raises(httpx.ConnectError, match=r"(?i)hostname"):
                    client.get(f"https://{host}:{port}/")
    profile.cleanup()


def test_governed_clients_pin_when_given_a_policy() -> None:
    inner, seen = _recording()
    options = HttpClientOptions(
        base_url=f"https://{PUBLIC}", retry=RetryPolicy(max_attempts=1), egress=UNTESTED
    )
    with create_http_client(options, transport=inner) as client:
        assert client.get("/x").status_code == 200
    assert seen[0].url.host == PUBLIC and seen[0].headers["host"] == PUBLIC


async def test_async_clients_pin_off_the_event_loop() -> None:
    resolver, calls = _dns((PUBLIC,))
    inner = httpx.MockTransport(lambda request: httpx.Response(204))
    transport = AsyncPinnedEgressTransport(inner, UNTESTED, resolver=resolver)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://api.example.com/")
    assert response.status_code == 204 and calls == ["api.example.com"]
    options = HttpClientOptions(base_url=f"https://{PUBLIC}", egress=UNTESTED)
    async with create_async_http_client(options, transport=inner) as governed:
        assert (await governed.get("/")).status_code == 204


def test_policy_and_options_validation() -> None:
    with pytest.raises(ValueError, match="exact hostnames"):
        EgressPolicy.for_hosts(["*.lab"])
    with pytest.raises(ValueError, match="too large"):
        EgressPolicy.for_hosts([f"h{i}.lab" for i in range(300)])
    proxied = ResolvedTLSProfile(
        name="p",
        source="inline",
        configured=True,
        system_trust=True,
        trust_env=False,
        ssl_context=ssl.create_default_context(),
        proxy_url="http://proxy.example:3128",
    )
    with pytest.raises(ValueError, match="proxy"):
        HttpClientOptions(base_url="https://a.example", tls=proxied, egress=UNTESTED)
