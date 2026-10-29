"""The SDK helpers that replace the retired agent-utilities harness modules."""

from __future__ import annotations

import httpx
import pytest

from agent_connector_sdk import exceptions, identity, utilities
from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.tls.resolve import resolve_tls_profile


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.1")
def test_actor_type_members_match_the_retired_enum() -> None:
    members = {member.name: member.value for member in identity.ActorType}
    assert members == {
        "HUMAN": "human",
        "AI_AGENT": "ai_agent",
        "AUTOMATED_SERVICE": "automated_service",
        "HYBRID_TEAM": "hybrid_team",
        "SYSTEM": "system",
    }


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.2")
def test_all_six_exceptions_keep_their_hierarchy() -> None:
    names = [
        "AuthError",
        "ApiError",
        "UnauthorizedError",
        "MissingParameterError",
        "ParameterError",
        "LoginRequiredError",
    ]
    for name in names:
        assert issubclass(getattr(exceptions, name), Exception)
    assert issubclass(exceptions.UnauthorizedError, exceptions.AuthError)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.3")
def test_governed_client_retries_an_idempotent_request() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503 if len(calls) == 1 else 200)

    options = HttpClientOptions(
        base_url="https://api.example.test",
        retry=RetryPolicy(max_attempts=2, backoff_base=0, jitter=False),
    )
    with create_http_client(options, transport=httpx.MockTransport(handler)) as client:
        assert client.get("/v1/ping").status_code == 200
    assert len(calls) == 2
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.4")
def test_tls_profile_resolver_is_exported() -> None:
    assert callable(resolve_tls_profile)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.5")
def test_value_coercions_and_logger() -> None:
    assert utilities.to_boolean("Yes") is True
    assert utilities.to_boolean("") is False
    assert utilities.to_integer("x") == 0
    assert utilities.to_float("1.5") == 1.5
    assert utilities.to_list("a,b") == ["a", "b"]
    assert utilities.get_logger("parity").name == "parity"
