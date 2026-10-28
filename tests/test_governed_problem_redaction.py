"""Governed response failures do not expose untrusted problem bodies."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_connector_sdk.http.client import create_async_http_client, create_http_client
from agent_connector_sdk.http.errors import HttpProblemError, HttpRateLimitedError
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.responses import arequest_json, request_json
from agent_connector_sdk.http.retry import RetryPolicy

_MARKER = "private-upstream-value"
_BODY = json.dumps(
    {
        "type": f"https://example.invalid/{_MARKER}",
        "title": _MARKER,
        "detail": _MARKER,
        "instance": _MARKER,
        "metadata": {"private": [_MARKER]},
    }
).encode()


def _reply(request: httpx.Request) -> httpx.Response:
    status = int(request.url.path.rsplit("/", 1)[-1])
    return httpx.Response(
        status,
        headers={"content-type": "application/problem+json", "retry-after": "3"},
        content=_BODY,
        request=request,
    )


def _options() -> HttpClientOptions:
    return HttpClientOptions(
        base_url="https://example.invalid", retry=RetryPolicy(max_attempts=1)
    )


def _check(error: HttpProblemError, status: int) -> None:
    if status == 429:
        assert isinstance(error, HttpRateLimitedError)
        assert error.retry_after == 3
    assert error.problem.status == status
    assert _MARKER not in str(error)
    assert _MARKER not in repr(error.problem)
    assert _MARKER not in json.dumps(error.problem.to_json())


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R006.1")
@pytest.mark.parametrize("status", (401, 429, 500))
def test_sync_governed_error_drops_problem_body(status: int) -> None:
    with (
        create_http_client(_options(), transport=httpx.MockTransport(_reply)) as client,
        pytest.raises(HttpProblemError) as caught,
    ):
        request_json(client, "GET", f"/data/{status}")
    _check(caught.value, status)


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R006.1")
@pytest.mark.parametrize("status", (401, 429, 500))
async def test_async_governed_error_drops_problem_body(status: int) -> None:
    async with create_async_http_client(
        _options(), transport=httpx.MockTransport(_reply)
    ) as client:
        with pytest.raises(HttpProblemError) as caught:
            await arequest_json(client, "GET", f"/data/{status}")
    _check(caught.value, status)
