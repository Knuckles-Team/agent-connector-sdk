"""SDK-CONNECTOR-CONTROL-R029: the structured AgentConfig singleton."""

from __future__ import annotations

import pytest

from agent_connector_sdk.config import (
    AgentConfig,
    AuthConfigSection,
    ConfigurationError,
    LimitsConfigSection,
    TransportConfigSection,
    agent_config,
)


def test_constructs_from_environment_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONNECTOR_AUTH_TOKEN_URL", "https://issuer.example.com/token")
    monkeypatch.setenv("CONNECTOR_AUTH_CLIENT_ID", "fleet-client")
    monkeypatch.setenv("CONNECTOR_TRANSPORT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("CONNECTOR_LIMITS_MAX_CONNECTIONS", "50")
    monkeypatch.setenv("CONNECTOR_LIMITS_MAX_KEEPALIVE_CONNECTIONS", "10")

    config = agent_config(reload=True)

    assert config.auth.token_url == "https://issuer.example.com/token"
    assert config.auth.client_id == "fleet-client"
    assert config.transport.timeout_seconds == 45
    assert config.limits.max_connections == 50
    assert config.limits.max_keepalive_connections == 10


@pytest.mark.parametrize(
    "section_factory",
    [
        lambda: TransportConfigSection(timeout_seconds=0),
        lambda: TransportConfigSection(timeout_seconds=-1),
        lambda: LimitsConfigSection(max_connections=0),
        lambda: LimitsConfigSection(max_keepalive_connections=0),
        lambda: LimitsConfigSection(max_connections=5, max_keepalive_connections=10),
    ],
)
def test_invalid_combinations_fail_at_construction(section_factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ConfigurationError):
        section_factory()


def test_singleton_accessor_returns_the_same_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONNECTOR_AUTH_TOKEN_URL", raising=False)
    first = agent_config(reload=True)
    second = agent_config()
    third = agent_config()
    assert first is second is third
    assert isinstance(first, AgentConfig)
    assert isinstance(first.auth, AuthConfigSection)
