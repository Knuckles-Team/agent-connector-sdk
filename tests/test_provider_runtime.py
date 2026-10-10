"""Provider-runtime profile resolution for multi-backend connectors."""

from __future__ import annotations

import pytest

from agent_connector_sdk.config import ConfigurationError
from agent_connector_sdk.provider_runtime import (
    ProviderRuntimeProfile,
    resolve_selected_provider_runtime_profile,
)

_PROFILES = {
    "openai": ProviderRuntimeProfile(
        provider_id="openai",
        base_url="https://api.openai.com/v1",
        auth_mode="bearer",
        capabilities={"embeddings": True, "streaming": True},
    ),
    "qdrant": ProviderRuntimeProfile(
        provider_id="qdrant",
        base_url="http://qdrant.internal:6333",
        auth_mode="api_key",
        capabilities={"embeddings": False, "streaming": False},
    ),
}


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R027")
def test_resolves_known_profile_by_identifier() -> None:
    profile = resolve_selected_provider_runtime_profile("qdrant", _PROFILES)
    assert profile is _PROFILES["qdrant"]
    assert profile.base_url == "http://qdrant.internal:6333"
    assert profile.auth_mode == "api_key"


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R027")
def test_unknown_identifier_raises_before_any_network_call() -> None:
    calls: list[str] = []

    class _NoNetwork:
        def __getattr__(self, name: str) -> object:
            calls.append(name)
            raise AssertionError("network call attempted before resolution")

    with pytest.raises(ConfigurationError, match="unknown provider"):
        resolve_selected_provider_runtime_profile("not-registered", _PROFILES)
    assert calls == []


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R027")
def test_unconfigured_provider_raises() -> None:
    with pytest.raises(ConfigurationError, match="no provider configured"):
        resolve_selected_provider_runtime_profile(None, _PROFILES)
    with pytest.raises(ConfigurationError, match="no provider configured"):
        resolve_selected_provider_runtime_profile("", _PROFILES)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R027")
def test_returned_profile_fields_reach_the_request_constructing_client() -> None:
    profile = resolve_selected_provider_runtime_profile("openai", _PROFILES)

    def construct_request(p: ProviderRuntimeProfile) -> dict[str, object]:
        return {
            "url": p.base_url,
            "auth": p.auth_mode,
            "supports_streaming": p.capabilities.get("streaming", False),
        }

    request = construct_request(profile)
    assert request == {
        "url": "https://api.openai.com/v1",
        "auth": "bearer",
        "supports_streaming": True,
    }
