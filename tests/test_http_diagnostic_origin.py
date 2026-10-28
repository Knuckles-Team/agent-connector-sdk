"""Governed diagnostics do not expose URL paths or query values."""

from __future__ import annotations

import logging
import traceback

import httpx
import pytest

from agent_connector_sdk.http.bodies import read_bounded
from agent_connector_sdk.http.client import (
    HTTP_LOGGER_NAME,
    create_async_http_client,
    create_http_client,
)
from agent_connector_sdk.http.errors import HttpProblemError, ResponseTooLargeError
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.redaction import redact_origin
from agent_connector_sdk.http.responses import arequest_json, request_json
from agent_connector_sdk.http.retry import RetryPolicy

_MARK = "sensitive-marker"
_URL = f"https://example.invalid/{_MARK}?item={_MARK}"


def _options() -> HttpClientOptions:
    return HttpClientOptions(
        base_url="https://example.invalid", retry=RetryPolicy(max_attempts=1)
    )


def _fail(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(_MARK, request=request)


def _invalid(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=f"{{{_MARK}", request=request)


def _check(error: HttpProblemError, caplog: pytest.LogCaptureFixture) -> None:
    assert _MARK not in caplog.text
    assert _MARK not in str(error.problem.to_json())
    assert _MARK not in "".join(traceback.format_exception(error))
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R006.3")
@pytest.mark.parametrize("handler", (_fail, _invalid))
def test_sync_diagnostics_omit_path_query_and_cause(handler, caplog) -> None:
    caplog.set_level(logging.INFO, logger=HTTP_LOGGER_NAME)
    with (
        create_http_client(
            _options(), transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(HttpProblemError) as caught,
    ):
        request_json(client, "GET", _URL)
    _check(caught.value, caplog)


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R006.3")
@pytest.mark.parametrize("handler", (_fail, _invalid))
async def test_async_diagnostics_omit_path_query_and_cause(handler, caplog) -> None:
    caplog.set_level(logging.INFO, logger=HTTP_LOGGER_NAME)
    async with create_async_http_client(
        _options(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(HttpProblemError) as caught:
            await arequest_json(client, "GET", _URL)
    _check(caught.value, caplog)


def test_origin_redaction_keeps_ipv6_port_without_user_information() -> None:
    userinfo = ":".join(("user", "pw"))
    assert (
        redact_origin(f"https://{userinfo}@[::1]:8443/path?x=y") == "https://[::1]:8443"
    )
    assert redact_origin("https://example.invalid:bad/path") == "<invalid-url>"


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R006.3")
def test_body_limit_diagnostic_omits_path() -> None:
    response = httpx.Response(200, content=b"12345", request=httpx.Request("GET", _URL))
    with pytest.raises(ResponseTooLargeError) as caught:
        read_bounded(response, 4)
    assert _MARK not in str(caught.value.problem.to_json())
