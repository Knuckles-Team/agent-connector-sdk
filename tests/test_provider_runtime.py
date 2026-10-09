"""SDK-CONNECTOR-CONTROL-R027: selecting a multi-backend provider runtime profile."""

from __future__ import annotations

import pytest

from agent_connector_sdk.manifest.provider_runtime import (
    ProviderRuntimeProfile,
    UnknownProviderRuntimeError,
    resolve_selected_provider_runtime_profile,
)

_SELF_HOSTED = ProviderRuntimeProfile(
    identifier="self-hosted",
    base_url="https://self-hosted.example.internal",
    auth_mode="api_key",
    capabilities=frozenset({"bulk_export"}),
)
_MANAGED = ProviderRuntimeProfile(
    identifier="managed",
    base_url="https://managed.example.com",
    auth_mode="oauth2",
)
_PROFILES = {"self-hosted": _SELF_HOSTED, "managed": _MANAGED}


def test_resolves_a_known_profile_by_identifier() -> None:
    profile = resolve_selected_provider_runtime_profile("managed", _PROFILES)
    assert profile is _MANAGED
    assert profile.base_url == "https://managed.example.com"
    assert profile.auth_mode == "oauth2"


def test_unknown_identifier_raises_before_any_network_call() -> None:
    with pytest.raises(UnknownProviderRuntimeError):
        resolve_selected_provider_runtime_profile("does-not-exist", _PROFILES)


@pytest.mark.parametrize("selected", [None, ""])
def test_unconfigured_provider_raises(selected: str | None) -> None:
    with pytest.raises(UnknownProviderRuntimeError):
        resolve_selected_provider_runtime_profile(selected, _PROFILES)


def test_returned_profile_fields_reach_the_client() -> None:
    profile = resolve_selected_provider_runtime_profile("self-hosted", _PROFILES)
    assert profile.identifier == "self-hosted"
    assert profile.capabilities == frozenset({"bulk_export"})
