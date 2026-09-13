"""Retry policy, Retry-After, redaction, problem details and the attempt flow."""

from __future__ import annotations

import logging
import ssl
from datetime import UTC, datetime

import httpx
import pytest

from agent_connector_sdk.exceptions import ApiError, UnauthorizedError
from agent_connector_sdk.http.errors import (
    HttpProblemError,
    HttpRateLimitedError,
    HttpUnauthorizedError,
    RetriesExhaustedError,
    TlsVerificationError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
    error_for_response,
    error_for_transport_failure,
)
from agent_connector_sdk.http.flow import (
    AttemptFlow,
    Done,
    Outcome,
    Pause,
    advance,
    attempt_flow,
)
from agent_connector_sdk.http.problems import (
    PROBLEM_JSON,
    SDK_PROBLEM_TYPE_PREFIX,
    ProblemDetails,
    problem_from_response,
)
from agent_connector_sdk.http.redaction import (
    REDACTED,
    is_sensitive_name,
    redact_headers,
    redact_url,
)
from agent_connector_sdk.http.retry import (
    IDEMPOTENT_METHODS,
    RETRYABLE_STATUSES,
    RetryPolicy,
    is_tls_verification_failure,
    parse_retry_after,
)

_URL = "https://api.example.invalid/items"


def test_advance_returns_done_instead_of_stop_iteration() -> None:
    request = httpx.Request("GET", _URL)
    flow = attempt_flow(RetryPolicy(), request, logging.getLogger("test.flow"))
    assert advance(flow, None) is None
    done = advance(flow, httpx.Response(200))
    assert isinstance(done, Done) and done.response.status_code == 200


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers, request=httpx.Request("GET", _URL))


def test_parse_retry_after_forms() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after("Thu, 01 Jan 2026 12:00:30 GMT", now=now) == 30.0
    assert parse_retry_after("Thu, 01 Jan 2026 11:00:00 GMT", now=now) == 0.0
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None


def test_retry_policy_validation_and_backoff() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(retry_methods=frozenset({"POST"}))
    with pytest.raises(ValueError):
        RetryPolicy(backoff_base=float("inf"))
    fixed = RetryPolicy(jitter=False, backoff_base=1.0, max_backoff=3.0)
    assert [fixed.backoff(n) for n in (1, 2, 3)] == [1.0, 2.0, 3.0]
    jittered = RetryPolicy(backoff_base=2.0).backoff(1)
    assert 1.0 <= jittered <= 2.0
    assert "POST" not in IDEMPOTENT_METHODS and 429 in RETRYABLE_STATUSES


def test_retry_policy_decisions() -> None:
    policy = RetryPolicy(jitter=False, max_retry_after=10.0)
    get, post = httpx.Request("GET", _URL), httpx.Request("POST", _URL)
    limited = httpx.Response(429, headers={"Retry-After": "4"})
    assert policy.delay_after_response(get, limited, 1) == 4.0
    assert policy.delay_after_response(post, limited, 1) is None
    assert policy.delay_after_response(get, limited, 3) is None
    too_long = httpx.Response(503, headers={"Retry-After": "60"})
    assert policy.delay_after_response(get, too_long, 1) is None
    assert policy.delay_after_response(get, httpx.Response(503), 1) == 0.5
    assert policy.delay_after_response(get, httpx.Response(404), 1) is None
    assert policy.delay_after_error(post, httpx.ConnectError("refused"), 1) == 0.5
    assert policy.delay_after_error(post, httpx.ReadTimeout("slow"), 1) is None
    assert policy.delay_after_error(get, httpx.ReadTimeout("slow"), 1) == 0.5
    verify = httpx.ConnectError("handshake")
    verify.__cause__ = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
    assert is_tls_verification_failure(verify)
    assert policy.delay_after_error(get, verify, 1) is None


def test_redaction() -> None:
    assert is_sensitive_name("Authorization") and is_sensitive_name("PRIVATE-TOKEN")
    assert not is_sensitive_name("Accept")
    headers = redact_headers({"Authorization": "Bearer abc", "Accept": "json"}.items())
    assert headers == {"Authorization": REDACTED, "Accept": "json"}
    userinfo = ":".join(("user", "pw"))
    url = redact_url(
        f"https://{userinfo}@api.example.invalid:8443/x?api_key=abc&page=2"
    )
    assert url == f"https://api.example.invalid:8443/x?api_key={REDACTED}&page=2"
    assert "pw" not in url and "abc" not in url


def test_problem_details_parsing() -> None:
    body = b'{"type": "https://e.invalid/p", "title": "Nope", "status": 400, "code": 7}'
    problem = problem_from_response(
        _response(409, headers={"Content-Type": f"{PROBLEM_JSON}; charset=utf-8"}), body
    )
    assert (problem.type, problem.title, problem.status) == (
        "https://e.invalid/p",
        "Nope",
        409,
    )
    assert problem.extensions == {"code": 7}
    assert problem.to_json()["code"] == 7
    malformed = problem_from_response(
        _response(500, headers={"Content-Type": PROBLEM_JSON}), b'{"title": 3}'
    )
    assert malformed.extensions == {"malformed_problem": True}
    assert malformed.title == "Internal Server Error"
    not_json = problem_from_response(
        _response(502, headers={"Content-Type": PROBLEM_JSON}), b"<"
    )
    assert not_json.extensions == {"malformed_problem": True}
    plain = problem_from_response(_response(418), b'{"secret": "echo"}')
    assert plain == ProblemDetails.for_status(418)
    sdk = ProblemDetails.sdk("timeout", "Timed out", detail="x" * 5000, attempts=2)
    assert (
        sdk.type.startswith(SDK_PROBLEM_TYPE_PREFIX) and len(sdk.detail or "") == 2048
    )


def test_error_for_response_classes() -> None:
    assert error_for_response(_response(204), b"") is None
    unauthorized = error_for_response(_response(401), b"")
    assert isinstance(unauthorized, HttpUnauthorizedError)
    assert isinstance(unauthorized, UnauthorizedError) and isinstance(
        unauthorized, ApiError
    )
    limited = error_for_response(_response(429, headers={"Retry-After": "3"}), b"")
    assert isinstance(limited, HttpRateLimitedError) and limited.retry_after == 3.0
    bare_limit = error_for_response(_response(429), b"")
    assert (
        isinstance(bare_limit, HttpRateLimitedError) and bare_limit.retry_after is None
    )
    generic = error_for_response(_response(500), b"")
    assert type(generic) is HttpProblemError


def test_error_for_transport_failure_classes() -> None:
    request = httpx.Request("GET", f"{_URL}?token=secret")
    timeout = error_for_transport_failure(httpx.ReadTimeout("t"), request, attempts=1)
    assert isinstance(timeout, UpstreamTimeoutError)
    assert "secret" not in (timeout.problem.detail or "")
    assert isinstance(
        error_for_transport_failure(httpx.ConnectError("c"), request, attempts=1),
        UpstreamUnavailableError,
    )
    exhausted = error_for_transport_failure(httpx.ReadError("r"), request, attempts=3)
    assert isinstance(exhausted, RetriesExhaustedError)
    assert exhausted.problem.extensions["attempts"] == 3
    other = error_for_transport_failure(httpx.ReadError("r"), request, attempts=1)
    assert other.problem.type.endswith("transport-failed")
    verify = httpx.ConnectError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
    )
    assert isinstance(
        error_for_transport_failure(verify, request, attempts=1), TlsVerificationError
    )


def test_attempt_flow_retries_then_returns(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="test.flow")
    request = httpx.Request("GET", f"{_URL}?access_token=hunter2")
    flow: AttemptFlow = attempt_flow(
        RetryPolicy(jitter=False), request, logging.getLogger("test.flow")
    )
    assert next(flow) is None
    busy: Outcome = httpx.Response(503)
    pause = flow.send(busy)
    assert isinstance(pause, Pause) and pause.seconds == 0.5 and pause.discard is busy
    assert next(flow) is None
    with pytest.raises(StopIteration) as done:
        flow.send(httpx.Response(200))
    assert done.value.value.status_code == 200
    assert len(caplog.records) == 2 and "hunter2" not in caplog.text
    assert caplog.records[0].levelno == logging.WARNING


def test_attempt_flow_raises_mapped_error() -> None:
    request = httpx.Request("POST", _URL)
    flow = attempt_flow(RetryPolicy(), request, logging.getLogger("test.flow"))
    next(flow)
    with pytest.raises(UpstreamTimeoutError) as raised:
        flow.send(httpx.ReadTimeout("slow"))
    assert isinstance(raised.value.__cause__, httpx.ReadTimeout)
