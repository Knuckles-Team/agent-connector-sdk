"""The egress guard refuses private, metadata and malformed destinations."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from agent_connector_sdk.http.egress import (
    MAX_RESOLVED_ADDRESSES,
    EgressDecision,
    egress_ip_is_blocked,
    resolve_host,
    validate_egress_url,
    validate_resolved_egress_url,
)
from agent_connector_sdk.http.egress_policy import EgressPolicy


def _with_userinfo(url: str) -> str:
    """A synthetic ``user:password@`` URL, assembled so no credential literal exists."""
    scheme, rest = url.split("://", 1)
    return f"{scheme}://{':'.join(('user', 'pw'))}@{rest}"


def _answers(*ips: str) -> Any:
    def resolve(host: str, port: Any) -> list[Any]:
        return [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in ips]

    return resolve


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", "empty url"),
        ("ftp://files.example.com/x", "unsupported scheme"),
        (_with_userinfo("https://api.example.com"), "credentials"),
        ("https:///path", "missing host"),
        ("https://api.example.com:99999", "invalid port"),
        ("http://10.1.2.3/upload", "blocked IP literal"),
        ("http://169.254.169.254/latest", "blocked IP literal"),
    ],
)
def test_syntactic_refusals(url: str, reason: str) -> None:
    decision = validate_egress_url(url)
    assert not decision.allowed and reason in decision.reason


def test_literals_and_hostnames() -> None:
    assert validate_egress_url("https://93.184.216.34/x") == EgressDecision(
        True, "allowed IP literal", ("93.184.216.34",)
    )
    assert validate_egress_url("http://127.0.0.1:8080").allowed
    assert not validate_egress_url("http://127.0.0.1", allow_loopback=False).allowed
    assert validate_egress_url("https://upload.example.com").resolved_ips == ()
    assert egress_ip_is_blocked("not-an-ip", allow_loopback=True)


def test_pinned_policy_uses_exact_config_host_validation() -> None:
    policy = EgressPolicy.for_hosts(["Example.Invalid."])
    assert policy.allowed_private_hosts == frozenset({"example.invalid"})
    with pytest.raises(ValueError, match="exact hostnames"):
        EgressPolicy.for_hosts(["bad..invalid"])


def test_resolution_checks_every_address() -> None:
    allowed = validate_resolved_egress_url(
        "https://upload.example.com",
        resolver=_answers("93.184.216.34", "93.184.216.34"),
    )
    assert allowed.allowed and allowed.resolved_ips == ("93.184.216.34",)
    rebinding = validate_resolved_egress_url(
        "https://upload.example.com", resolver=_answers("93.184.216.34", "10.0.0.5")
    )
    assert rebinding.reason == "resolves to blocked address"
    flood = _answers(*["93.184.216.34"] * (MAX_RESOLVED_ADDRESSES + 1))
    assert not validate_resolved_egress_url(
        "https://a.example.com", resolver=flood
    ).allowed
    assert not validate_resolved_egress_url(
        "https://a.example.com", resolver=_answers()
    ).allowed


def test_resolution_failures_refuse() -> None:
    def broken(host: str, port: Any) -> list[Any]:
        raise OSError("no dns")

    assert (
        validate_resolved_egress_url("https://a.example.com", resolver=broken).reason
        == "DNS resolution failed"
    )
    garbage = validate_resolved_egress_url(
        "https://a.example.com", resolver=lambda host, port: [("bad",)]
    )
    assert garbage.reason == "invalid address resolved"
    literal = validate_resolved_egress_url("https://93.184.216.34")
    assert literal.resolved_ips == ("93.184.216.34",)


def test_resolve_host_lists_distinct_addresses_without_judging_them() -> None:
    decision = resolve_host(
        "svc.example", resolver=_answers("10.0.0.5", "10.0.0.5", "10.0.0.6")
    )
    assert decision == EgressDecision(True, "resolved", ("10.0.0.5", "10.0.0.6"))
