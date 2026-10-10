"""SDK-CONNECTOR-CONTROL-R028.1: the SSRF egress policy check and pinned transport."""

from __future__ import annotations

import httpx
import pytest

from agent_connector_sdk.http.egress import (
    EgressPolicyError,
    PinnedAddressTransport,
    check_egress_destination,
    pinned_egress_transport,
)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1"])
def test_private_and_loopback_destinations_rejected_by_default(host: str) -> None:
    with pytest.raises(EgressPolicyError):
        check_egress_destination(host)


def test_explicitly_allowed_private_host_passes() -> None:
    check_egress_destination("10.0.0.5", allowed_private_hosts={"10.0.0.5"})


def test_explicitly_allowed_loopback_passes() -> None:
    check_egress_destination("127.0.0.1", allow_loopback=True)


def test_public_destination_always_passes() -> None:
    check_egress_destination("api.example.com")


def test_pin_egress_false_disables_the_check_entirely() -> None:
    check_egress_destination("127.0.0.1", pin_egress=False)


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
