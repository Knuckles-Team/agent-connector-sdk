"""Exceptions that carry an RFC 9457 problem.

Every error the governed client raises is a :class:`HttpProblemError`, which is
an :class:`~agent_connector_sdk.exceptions.ApiError`; 401 and 403 are also
:class:`~agent_connector_sdk.exceptions.UnauthorizedError`, so connector
``except`` clauses written against the SDK exceptions keep their meaning.
"""

from __future__ import annotations

import httpx

from agent_connector_sdk.exceptions import ApiError, UnauthorizedError
from agent_connector_sdk.http.problems import ProblemDetails, problem_from_response
from agent_connector_sdk.http.redaction import redact_url
from agent_connector_sdk.http.retry import (
    is_tls_verification_failure,
    parse_retry_after,
)

__all__ = [
    "HttpProblemError",
    "HttpRateLimitedError",
    "HttpUnauthorizedError",
    "ResponseTooLargeError",
    "RetriesExhaustedError",
    "TlsVerificationError",
    "UpstreamTimeoutError",
    "UpstreamUnavailableError",
    "error_for_response",
    "error_for_transport_failure",
]


class HttpProblemError(ApiError):
    """An upstream call failed; ``problem`` describes how."""

    def __init__(self, problem: ProblemDetails) -> None:
        super().__init__(problem.title or problem.type)
        self.problem = problem


class HttpUnauthorizedError(HttpProblemError, UnauthorizedError):
    """The upstream rejected the credentials (401) or the access (403)."""


class HttpRateLimitedError(HttpProblemError):
    """The upstream answered 429; ``retry_after`` is in seconds when known."""

    @property
    def retry_after(self) -> float | None:
        """Seconds the upstream asked the caller to wait."""
        value = self.problem.extensions.get("retry_after")
        return float(value) if isinstance(value, int | float) else None


class UpstreamTimeoutError(HttpProblemError):
    """The upstream did not answer within the timeout."""


class UpstreamUnavailableError(HttpProblemError):
    """No connection to the upstream could be established."""


class TlsVerificationError(HttpProblemError):
    """The upstream's certificate did not verify against the TLS profile."""


class RetriesExhaustedError(HttpProblemError):
    """Every attempt the retry policy allowed failed."""


class ResponseTooLargeError(HttpProblemError):
    """A response body exceeded its size bound."""


def error_for_response(
    response: httpx.Response, body: bytes
) -> HttpProblemError | None:
    """The error an HTTP response represents, or ``None`` below status 400."""
    status = response.status_code
    if status < 400:
        return None
    if status in (401, 403):
        return HttpUnauthorizedError(problem_from_response(response, body))
    if status != 429:
        return HttpProblemError(problem_from_response(response, body))
    problem = problem_from_response(response, body)
    retry_after = parse_retry_after(response.headers.get("retry-after"))
    if retry_after is not None:
        extensions = {**problem.extensions, "retry_after": retry_after}
        problem = problem.model_copy(update={"extensions": extensions})
    return HttpRateLimitedError(problem)


def error_for_transport_failure(
    error: httpx.TransportError, request: httpx.Request, *, attempts: int
) -> HttpProblemError:
    """The error a transport failure represents after ``attempts`` attempts."""
    target = f"{request.method} {redact_url(request.url)}"
    cause = type(error).__name__
    if is_tls_verification_failure(error):
        return TlsVerificationError(
            ProblemDetails.sdk(
                "tls-verification-failed",
                "Certificate verification failed",
                detail=target,
            )
        )
    if attempts > 1:
        return RetriesExhaustedError(
            ProblemDetails.sdk(
                "retries-exhausted",
                "Retries exhausted",
                detail=target,
                attempts=attempts,
                cause=cause,
            )
        )
    if isinstance(error, httpx.TimeoutException):
        return UpstreamTimeoutError(
            ProblemDetails.sdk(
                "timeout", "Upstream timed out", detail=target, cause=cause
            )
        )
    if isinstance(error, httpx.ConnectError):
        return UpstreamUnavailableError(
            ProblemDetails.sdk(
                "unavailable", "Upstream unavailable", detail=target, cause=cause
            )
        )
    return HttpProblemError(
        ProblemDetails.sdk(
            "transport-failed", "Upstream transport failed", detail=target, cause=cause
        )
    )
