"""Configuration-only source URL admission; transport pinning is separate."""

from __future__ import annotations

import pytest

from agent_connector_sdk.http.source_egress import (
    SourceEgressError,
    normalize_allowed_hosts,
    require_safe_source_url,
)


def test_exact_private_host_exceptions_are_normalized() -> None:
    assert normalize_allowed_hosts(
        ["LOCALHOST.", "bücher.example", "::1"]
    ) == frozenset({"localhost", "xn--bcher-kva.example", "::1"})
    for host in ("*.example.com", "https://example.com", "user@host"):
        with pytest.raises(SourceEgressError):
            normalize_allowed_hosts([host])


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://[::1]",
        "http://169.254.169.254",
        "https://user@example.com",
        "https://example.com/#fragment",
        "https://example.com:0",
        "https://example.com\\path",
    ],
)
def test_unapproved_private_or_malformed_source_url_is_rejected(url: str) -> None:
    with pytest.raises(SourceEgressError):
        require_safe_source_url(url)


def test_source_url_admission_is_exact_and_does_not_resolve_dns() -> None:
    assert require_safe_source_url("https://example.com/path") == "example.com"
    assert (
        require_safe_source_url("http://127.0.0.1", allowed_private_hosts={"127.0.0.1"})
        == "127.0.0.1"
    )
    assert require_safe_source_url("http://100.64.0.1") == "100.64.0.1"
