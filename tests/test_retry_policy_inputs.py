"""Retry policy snapshots caller-owned sets and rejects malformed controls."""

from __future__ import annotations

import logging

import httpx
import pytest

from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.http.transport import AsyncGovernedTransport, GovernedTransport


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.6")
@pytest.mark.parametrize("attempts", [True, False, 2.5, "2", None])
def test_retry_policy_rejects_non_integer_attempts(attempts):
    with pytest.raises(ValueError, match="attempts must be an integer"):
        RetryPolicy(max_attempts=attempts)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.6")
@pytest.mark.parametrize("jitter", [0, 1, "false", None])
def test_retry_policy_rejects_non_boolean_jitter(jitter):
    with pytest.raises(ValueError, match="jitter must be a boolean"):
        RetryPolicy(jitter=jitter)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.6")
def test_mutable_input_cannot_enable_post_retry():
    methods, statuses = {"GET"}, {503}
    policy = RetryPolicy(retry_methods=methods, retry_statuses=statuses, jitter=False)
    methods.add("POST")
    statuses.clear()
    calls = []

    def respond(request):
        calls.append(request.method)
        return httpx.Response(503)

    transport = GovernedTransport(
        httpx.MockTransport(respond), policy=policy, logger=logging.getLogger(__name__)
    )
    with httpx.Client(transport=transport) as client:
        assert client.post("https://example.test/resource").status_code == 503
    assert calls == ["POST"]
    assert policy.retry_methods == frozenset({"GET"})
    assert policy.retry_statuses == frozenset({503})


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R028.6")
async def test_async_mutable_input_cannot_enable_post_retry():
    methods = {"GET"}
    policy = RetryPolicy(retry_methods=methods, jitter=False)
    methods.add("POST")
    calls = []

    async def respond(request):
        calls.append(request.method)
        return httpx.Response(503)

    transport = AsyncGovernedTransport(
        httpx.MockTransport(respond), policy=policy, logger=logging.getLogger(__name__)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert (await client.post("https://example.test/resource")).status_code == 503
    assert calls == ["POST"]
