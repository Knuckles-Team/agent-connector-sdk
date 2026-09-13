"""Conformance checks for a connector's governed HTTP client.

A connector passes a factory that builds its API client the way the connector
does in production, pointed at a base URL the kit chooses. The kit runs a local
scripted server and checks the behaviours the SDK guarantees: finite timeouts,
``Retry-After`` honoured on idempotent requests, problem details mapped to
errors, certificate verification enforced and secrets absent from request logs.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from agent_connector_sdk.http.client import HTTP_LOGGER_NAME
from agent_connector_sdk.http.errors import HttpProblemError, TlsVerificationError
from agent_connector_sdk.http.problems import PROBLEM_JSON
from agent_connector_sdk.http.responses import request_json
from agent_connector_sdk.testing.certificates import issue_test_certificates
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from agent_connector_sdk.testing.results import ConformanceResult

__all__ = [
    "HttpClientFactory",
    "check_finite_timeout",
    "check_problem_mapping",
    "check_rate_limit_retry",
    "check_secret_redaction",
    "check_tls_verification",
    "run_http_client_suite",
]

#: Builds the connector's client for a base URL.
HttpClientFactory = Callable[[str], httpx.Client]

_PROBE_VALUE = "conformance-probe-value"


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.texts: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.texts.append(f"{record.getMessage()} {record.__dict__}")


def check_finite_timeout(factory: HttpClientFactory) -> ConformanceResult:
    """Every timeout of the client is finite."""
    with factory("https://api.example.invalid") as client:
        timeout = client.timeout
    values = (timeout.connect, timeout.read, timeout.write, timeout.pool)
    passed = all(value is not None for value in values)
    return ConformanceResult(
        "finite-timeout", passed, "" if passed else "a timeout is unbounded"
    )


def check_rate_limit_retry(factory: HttpClientFactory) -> ConformanceResult:
    """A GET answered 429 with ``Retry-After: 0`` is retried and then succeeds."""
    limited = ScriptedResponse(status=429, headers={"Retry-After": "0"})
    with ScriptedHttpServer(limited, ScriptedResponse(body=b"{}")) as server:
        with factory(server.base_url) as client:
            status = client.get("/conformance").status_code
        attempts = len(server.requests)
    passed = status == 200 and attempts == 2
    return ConformanceResult(
        "rate-limit-retry", passed, f"status {status} after {attempts} attempts"
    )


def check_problem_mapping(factory: HttpClientFactory) -> ConformanceResult:
    """A problem+json 404 surfaces as :class:`HttpProblemError` with its details."""
    body = b'{"type": "https://api.example.invalid/missing", "title": "Missing"}'
    missing = ScriptedResponse(
        status=404, body=body, headers={"Content-Type": PROBLEM_JSON}
    )
    with ScriptedHttpServer(missing) as server, factory(server.base_url) as client:
        try:
            request_json(client, "GET", "/conformance")
        except HttpProblemError as error:
            passed = error.problem.status == 404 and error.problem.title == "Missing"
            return ConformanceResult("problem-mapping", passed, error.problem.type)
    return ConformanceResult("problem-mapping", False, "a 404 did not raise")


def check_secret_redaction(factory: HttpClientFactory) -> ConformanceResult:
    """Request logs never contain a query-string credential."""
    handler, logger = _Records(), logging.getLogger(HTTP_LOGGER_NAME)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        with (
            ScriptedHttpServer(ScriptedResponse()) as server,
            factory(server.base_url) as client,
        ):
            client.get("/conformance", params={"access_token": _PROBE_VALUE})
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    leaked = any(_PROBE_VALUE in text for text in handler.texts)
    passed = bool(handler.texts) and not leaked
    return ConformanceResult(
        "secret-redaction", passed, "" if passed else "no log or secret leaked"
    )


def check_tls_verification(factory: HttpClientFactory) -> ConformanceResult:
    """A server certificate from an untrusted CA fails with :class:`TlsVerificationError`."""
    certificates = issue_test_certificates()
    with tempfile.TemporaryDirectory() as directory:
        context = certificates.server_context(Path(directory))
        server = ScriptedHttpServer(ScriptedResponse(), ssl_context=context)
        with server, factory(server.base_url) as client:
            return _tls_probe(client)


def _tls_probe(client: httpx.Client) -> ConformanceResult:
    try:
        client.get("/conformance")
    except TlsVerificationError:
        return ConformanceResult("tls-verification", True)
    except httpx.HTTPError as error:
        detail = f"{type(error).__name__} instead of TlsVerificationError"
        return ConformanceResult("tls-verification", False, detail)
    return ConformanceResult(
        "tls-verification", False, "untrusted certificate was accepted"
    )


def run_http_client_suite(factory: HttpClientFactory) -> list[ConformanceResult]:
    """Run every HTTP client check."""
    return [
        check_finite_timeout(factory),
        check_rate_limit_retry(factory),
        check_problem_mapping(factory),
        check_secret_redaction(factory),
        check_tls_verification(factory),
    ]
