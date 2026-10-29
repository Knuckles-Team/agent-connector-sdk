"""SDK-CONNECTOR-CONTROL-R030.1: the shared GraphQL client."""

from __future__ import annotations

import base64
from dataclasses import replace
from typing import Any

import pytest
from gql.transport.exceptions import TransportQueryError, TransportServerError

from agent_connector_sdk.exceptions import ParameterError
from agent_connector_sdk.tls.resolve import resolve_tls_profile
from agent_connector_sdk.transports.graphql import (
    RETRYABLE_STATUS,
    GraphQLAuth,
    GraphQLClient,
    GraphQLExecutionError,
)

pytestmark = pytest.mark.spec("SDK-CONNECTOR-CONTROL-R030.1")

_QUERY = "query { viewer { login } }"


class _FakeExecution:
    def __init__(self, data: Any, errors: list[Any]) -> None:
        self.data = data
        self.errors = errors


class _FakeProtocolClient:
    """Stands in for the protocol client: replays scripted outcomes."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def execute(self, _query: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _client(
    outcomes: list[Any], **kwargs: Any
) -> tuple[GraphQLClient, _FakeProtocolClient, list[float]]:
    sleeps: list[float] = []
    client = GraphQLClient(
        "https://example.invalid/graphql",
        auth=GraphQLAuth.bearer("secret-token"),
        tls_profile=resolve_tls_profile("graphql"),
        sleep=sleeps.append,
        **kwargs,
    )
    fake = _FakeProtocolClient(outcomes)
    client._client = fake
    return client, fake, sleeps


def test_auth_header_strategies() -> None:
    assert GraphQLAuth.bearer("t").headers() == {"Authorization": "Bearer t"}
    assert GraphQLAuth.token("t").headers() == {"Authorization": "token t"}
    assert GraphQLAuth.token("t", header="PRIVATE-TOKEN", prefix="").headers() == {
        "PRIVATE-TOKEN": "t"
    }
    basic = GraphQLAuth.basic("u", "p").headers()["Authorization"]
    assert basic == "Basic " + base64.b64encode(b"u:p").decode()
    assert GraphQLAuth.none().headers() == {}
    assert "secret" not in repr(GraphQLAuth.bearer("secret"))


def test_headers_merge_extra_and_auth() -> None:
    client = GraphQLClient(
        "https://example.invalid/graphql",
        auth=GraphQLAuth.bearer("t"),
        headers={"Origin": "https://example.invalid"},
        tls_profile=resolve_tls_profile("graphql"),
    )
    assert client.headers == {
        "Origin": "https://example.invalid",
        "Authorization": "Bearer t",
    }


def test_execute_returns_data_and_passes_variables() -> None:
    client, fake, _ = _client([{"viewer": {"login": "a"}}])
    assert client.execute(_QUERY, {"x": 1}, "Op") == {"viewer": {"login": "a"}}
    assert fake.calls[0]["variable_values"] == {"x": 1}
    assert fake.calls[0]["operation_name"] == "Op"


def test_retries_429_and_5xx_then_succeeds() -> None:
    assert {429, 502, 503} <= RETRYABLE_STATUS and 400 not in RETRYABLE_STATUS
    client, fake, sleeps = _client(
        [
            TransportServerError("busy", 429),
            TransportServerError("down", 503),
            {"ok": True},
        ],
        max_retries=2,
        backoff=0.5,
    )
    assert client.execute(_QUERY) == {"ok": True}
    assert sleeps == [0.5, 1.0]
    assert len(fake.calls) == 3


def test_retry_is_bounded_and_failure_is_redacted() -> None:
    client, fake, sleeps = _client(
        [TransportServerError("secret-token leaked body", 502)] * 3, max_retries=2
    )
    with pytest.raises(GraphQLExecutionError) as caught:
        client.execute(_QUERY)
    assert len(fake.calls) == 3 and len(sleeps) == 2
    error = caught.value
    assert isinstance(error, ParameterError)
    assert str(error) == "Query execution failed: TransportServerError"
    payload = error.payload()
    assert payload["code"] == "operation_failed"
    assert payload["retryable"] is True
    assert payload["error_class"] == "TransportServerError"
    assert len(payload["correlation_id"]) == 32
    assert "secret" not in str(payload)


def test_non_retryable_failure_is_not_retried() -> None:
    client, fake, sleeps = _client(
        [TransportServerError("bad", 400), TransportQueryError("x")]
    )
    with pytest.raises(GraphQLExecutionError) as caught:
        client.execute(_QUERY)
    assert caught.value.payload()["retryable"] is False
    assert len(fake.calls) == 1 and sleeps == []
    with pytest.raises(GraphQLExecutionError, match="TransportQueryError"):
        client.execute(_QUERY)


def test_allow_partial_returns_data_and_counts_errors() -> None:
    client, _, _ = _client(
        [_FakeExecution({"a": 1}, ["e1", "e2"]), _FakeExecution(None, ["e"])]
    )
    assert client.execute(_QUERY, allow_partial=True) == {"a": 1}
    assert client.last_partial_error_count == 2
    with pytest.raises(GraphQLExecutionError):
        client.execute(_QUERY, allow_partial=True)


def test_paginate_follows_cursors_nodes_and_edges() -> None:
    pages = [
        {
            "project": {
                "issues": {
                    "nodes": [{"id": 1}, {"id": 2}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                }
            }
        },
        {
            "project": {
                "issues": {
                    "edges": [{"node": {"id": 3}}],
                    "pageInfo": {"hasNextPage": False, "endCursor": "c2"},
                }
            }
        },
    ]
    client, fake, _ = _client(pages)
    nodes = list(client.paginate(_QUERY, ("project", "issues"), {"first": 2}))
    assert [n["id"] for n in nodes] == [1, 2, 3]
    assert fake.calls[1]["variable_values"] == {"first": 2, "after": "c1"}


def test_paginate_is_bounded_by_max_pages() -> None:
    endless = {
        "c": {"nodes": [{"id": 1}], "pageInfo": {"hasNextPage": True, "endCursor": "x"}}
    }
    client, fake, _ = _client([endless] * 5)
    assert len(list(client.paginate(_QUERY, ("c",), max_pages=3))) == 3
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_execute_async_matches_sync() -> None:
    client, _, _ = _client([{"ok": 1}])
    assert await client.execute_async(_QUERY) == {"ok": 1}


def test_builds_protocol_client_with_tls_timeout_and_schema_flag() -> None:
    client = GraphQLClient(
        "https://example.invalid/graphql",
        tls_profile=resolve_tls_profile("graphql"),
        timeout=7,
        fetch_schema=True,
    )
    built = client.client
    assert built.fetch_schema_from_transport is True
    assert built.transport.url == "https://example.invalid/graphql"
    assert built.transport.default_timeout == 7
    assert client.schema is None
    client.close()


def test_invalid_configuration_refuses() -> None:
    with pytest.raises(ParameterError):
        GraphQLClient("", tls_profile=resolve_tls_profile("graphql"))
    with pytest.raises(ParameterError):
        GraphQLClient(
            "https://e.invalid",
            max_retries=99,
            tls_profile=resolve_tls_profile("graphql"),
        )


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R006.5")
def test_close_suppresses_upstream_details_and_cleans_tls(caplog, tmp_path) -> None:
    client, _, _ = _client([])
    material = tmp_path / "key.pem"
    material.write_text("private runtime key")
    client.tls_profile = replace(client.tls_profile, materialized=(material,))

    class BrokenClient:
        session = object()

        def close_sync(self) -> None:
            raise RuntimeError("private bearer-token and response-body")

    client._client = BrokenClient()
    with caplog.at_level("DEBUG", logger="agent_connector_sdk.transports.graphql"):
        client.close()
    assert not material.exists()
    assert "GraphQL client close failed" in caplog.text
    assert "private" not in caplog.text
    assert "bearer-token" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
