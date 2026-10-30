"""Upstream GraphQL exceptions are not returned or logged."""

from __future__ import annotations

import logging
import traceback

import pytest

from scion_sdk.mcp.graphql import (
    ctx_graphql_get_type_details,
    ctx_graphql_list_types,
)
from scion_sdk.tls.resolve import resolve_tls_profile
from scion_sdk.transports.graphql import GraphQLClient, GraphQLExecutionError

_MARKER = "private-upstream-marker"


class _FailingClient:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError(_MARKER)


def _client() -> GraphQLClient:
    client = GraphQLClient(
        "https://example.invalid/graphql",
        tls_profile=resolve_tls_profile("graphql"),
        max_retries=0,
    )
    client._client = _FailingClient()
    return client


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R006.4")
def test_graphql_sync_failure_does_not_expose_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GraphQLExecutionError) as caught:
        _client().execute("query { x }")
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert _MARKER not in caplog.text
    assert _MARKER not in "".join(traceback.format_exception(caught.value))
    assert _MARKER not in str(caught.value.payload())
    assert caught.value.payload()["error_class"] == "RuntimeError"


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R006.4")
async def test_graphql_async_and_introspection_hide_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GraphQLExecutionError) as caught:
        await _client().execute_async("query { x }")

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError(_MARKER)

    failures = [
        await ctx_graphql_list_types(fail),
        await ctx_graphql_get_type_details(fail, "X"),
    ]
    assert all(value["error_class"] == "RuntimeError" for value in failures)
    assert _MARKER not in str(failures)
    assert _MARKER not in caplog.text
    assert _MARKER not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None and caught.value.__context__ is None
