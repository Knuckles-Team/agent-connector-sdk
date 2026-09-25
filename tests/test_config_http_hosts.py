"""The connector SDK owns exact outbound host exception validation."""

import pytest

from agent_connector_sdk.config import normalize_http_host_allowlist


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
