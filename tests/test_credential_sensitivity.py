"""Configuration sensitivity: which keys are redacted and which values are references."""

from __future__ import annotations

import pytest

from agent_connector_sdk.credentials.sensitivity import (
    configuration_key_is_sensitive,
    runtime_reference,
)


@pytest.mark.parametrize(
    ("key", "metadata", "sensitive"),
    [
        ("API_TOKEN", None, True),
        ("serviceBaseUrl", None, True),
        ("TLS_CA_BUNDLE", None, True),
        ("CLIENT_ID", None, True),
        ("SIGNING_KEY", None, True),
        ("MCP_CONFIG", None, True),
        ("MAX_PAGES", {"secret": True}, True),
        ("MAX_PAGES", None, False),
        ("CACHE_KEY_PREFIX", None, False),
        ("LOG_LEVEL", None, False),
    ],
)
def test_key_sensitivity(key: str, metadata: dict | None, sensitive: bool) -> None:
    assert configuration_key_is_sensitive(key, metadata) is sensitive


@pytest.mark.parametrize(
    ("value", "is_reference"),
    [
        ("${GITHUB_TOKEN}", True),
        ("vault://apps/x#token", True),
        ("env://TOKEN", True),
        ("${TOKEN:-literal}", False),
        ("plain-literal", False),
        (42, False),
    ],
)
def test_runtime_reference(value: object, is_reference: bool) -> None:
    assert runtime_reference(value) is is_reference
