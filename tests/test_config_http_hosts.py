"""The connector SDK owns exact outbound host exception validation."""

import pytest

from agent_connector_sdk.config import (
    normalize_http_host_allowlist,
    validate_http_base_url,
)


def test_normalizes_exact_hosts_without_widening() -> None:
    assert normalize_http_host_allowlist(
        ["Example.Invalid.", "example.invalid", "127.0.0.1", "api.example.invalid"]
    ) == ["127.0.0.1", "api.example.invalid", "example.invalid"]


@pytest.mark.parametrize(
    "host",
    [
        "",
        "*.example.invalid",
        "bad..invalid",
        "-bad.invalid",
        "bad-.invalid",
        "https://example.invalid",
        "bad/path",
        "bäd.invalid",
    ],
)
def test_rejects_non_exact_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="HTTP host allow-lists"):
        normalize_http_host_allowlist([host])


def test_rejects_oversize_allowlist() -> None:
    with pytest.raises(ValueError, match="at most 256"):
        normalize_http_host_allowlist(["host.invalid"] * 257)


def test_runtime_http_base_url_is_normalized_without_network_access() -> None:
    assert validate_http_base_url(None) is None
    assert validate_http_base_url(" HTTPS://Example.Invalid:8443/path/ ") == (
        "https://Example.Invalid:8443/path"
    )


@pytest.mark.parametrize(
    "value",
    [
        "ftp://example.invalid",
        "https://user:pass@example.invalid",
        "https://example.invalid:70000",
        "https://example.invalid/path?token=x",
        "https://example.invalid/#fragment",
        "https://{server}.invalid",
        "https://example.invalid/ bad",
        "https://example.invalid/" + "a" * 2_049,
    ],
)
def test_runtime_http_base_url_rejects_unsafe_authority(value: str) -> None:
    with pytest.raises(ValueError):
        validate_http_base_url(value)
