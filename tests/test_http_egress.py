"""SCION-CONNECTOR-CONTROL-R028.1: the SSRF egress policy check and pinned transport."""

from __future__ import annotations

import ssl
from pathlib import Path

import httpx
import pytest

from scion_sdk.http.egress import (
    EgressOptions,
    EgressPolicyError,
    PinnedAddressTransport,
    check_egress_destination,
    pinned_egress_transport,
)
from scion_sdk.testing.certificates import issue_test_certificates
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1"])
def test_private_and_loopback_destinations_rejected_by_default(host: str) -> None:
    with pytest.raises(EgressPolicyError):
        check_egress_destination(host)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
def test_explicitly_allowed_private_host_passes() -> None:
    check_egress_destination(
        "10.0.0.5", EgressOptions(allowed_private_hosts={"10.0.0.5"})
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
def test_explicitly_allowed_loopback_passes() -> None:
    check_egress_destination("127.0.0.1", EgressOptions(allow_loopback=True))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
@pytest.mark.parametrize("host", ["LOCALHOST", "localhost.", "LoCaLhOsT."])
def test_loopback_hostname_canonicalization(host: str) -> None:
    with pytest.raises(EgressPolicyError):
        check_egress_destination(host)
    check_egress_destination(host, EgressOptions(allow_loopback=True))
    check_egress_destination(host, EgressOptions(allowed_private_hosts={"LOCALHOST."}))
    with pytest.raises(EgressPolicyError):
        check_egress_destination(host, EgressOptions(allowed_private_hosts={"other"}))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
def test_public_destination_always_passes() -> None:
    check_egress_destination("api.example.com")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
def test_pin_egress_false_disables_the_check_entirely() -> None:
    check_egress_destination("127.0.0.1", EgressOptions(pin_egress=False))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
def test_pinned_transport_reuses_the_resolved_address_not_dns() -> None:
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        return httpx.Response(200, request=request)

    inner = httpx.MockTransport(handler)
    transport = pinned_egress_transport(host="203.0.113.9", port=443, inner=inner)
    assert isinstance(transport, PinnedAddressTransport)

    first = transport.handle_request(
        httpx.Request("GET", "https://api.example.com/first")
    )
    second = transport.handle_request(
        httpx.Request("GET", "https://api.example.com/second")
    )

    assert first.status_code == 200
    assert second.status_code == 200
    # Every request dialed the pinned address, never the request's own host.
    assert seen_hosts == ["203.0.113.9", "203.0.113.9"]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.1")
def test_pinned_transport_verifies_original_tls_hostname(tmp_path: Path) -> None:
    certificates = issue_test_certificates()
    server_context = certificates.server_context(tmp_path)
    observed_sni: list[str | None] = []
    server_context.set_servername_callback(
        lambda _socket, name, _context: observed_sni.append(name)
    )
    client_context = ssl.create_default_context(cadata=certificates.ca_pem)
    with ScriptedHttpServer(ScriptedResponse(), ssl_context=server_context) as server:
        port = int(server.base_url.rsplit(":", 1)[1])
        transport = pinned_egress_transport(
            host="127.0.0.1",
            port=port,
            inner=httpx.HTTPTransport(verify=client_context),
        )
        with httpx.Client(transport=transport, trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                client.get(
                    "https://invalid.example/", extensions={"sni_hostname": "localhost"}
                )
            response = client.get("https://localhost/")
    assert response.status_code == 200
    assert observed_sni == ["invalid.example", "localhost"]
    assert server.requests[0].headers["host"] == "localhost"
