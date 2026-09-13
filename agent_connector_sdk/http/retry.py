"""Bounded retries with exponential backoff, jitter and ``Retry-After``.

Only idempotent methods are retried after a response or a failure that may have
reached the server. A connection that was never established is retried for any
method, because the request was not sent. A certificate verification failure is
never retried.
"""

from __future__ import annotations

import math
import secrets
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

__all__ = [
    "IDEMPOTENT_METHODS",
    "RETRYABLE_STATUSES",
    "RetryPolicy",
    "is_tls_verification_failure",
    "parse_retry_after",
]

#: Methods RFC 9110 defines as idempotent.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE"})
#: Statuses that signal a transient condition.
RETRYABLE_STATUSES = frozenset({408, 429, 502, 503, 504})

_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_RANDOM = secrets.SystemRandom()


def parse_retry_after(
    value: str | None, *, now: datetime | None = None
) -> float | None:
    """Seconds to wait from a ``Retry-After`` value (delta-seconds or HTTP-date).

    Returns ``None`` for a missing or malformed value; a date in the past is ``0``.
    """
    rendered = (value or "").strip()
    if rendered.isdigit():
        return float(rendered)
    try:
        when = parsedate_to_datetime(rendered)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


def is_tls_verification_failure(error: BaseException) -> bool:
    """Whether ``error`` was caused by a certificate verification failure."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        if "CERTIFICATE_VERIFY_FAILED" in str(current):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


@dataclass(frozen=True)
class RetryPolicy:
    """How many attempts a request gets and how long to wait between them.

    Attributes:
        max_attempts: Total attempts including the first, 1 to 10.
        backoff_base: Delay before the second attempt, in seconds.
        backoff_factor: Multiplier applied per further attempt.
        max_backoff: Upper bound of a computed delay.
        max_retry_after: A ``Retry-After`` longer than this is not waited for;
            the response is returned to the caller instead.
        jitter: Randomize each computed delay between half and all of it.
        retry_statuses: Statuses retried for idempotent methods.
        retry_methods: Methods retried; must be idempotent.
    """

    max_attempts: int = 3
    backoff_base: float = 0.5
    backoff_factor: float = 2.0
    max_backoff: float = 30.0
    max_retry_after: float = 120.0
    jitter: bool = True
    retry_statuses: frozenset[int] = RETRYABLE_STATUSES
    retry_methods: frozenset[str] = IDEMPOTENT_METHODS

    def __post_init__(self) -> None:
        numbers = (
            self.backoff_base,
            self.backoff_factor,
            self.max_backoff,
            self.max_retry_after,
        )
        problems = (
            not 1 <= self.max_attempts <= 10,
            not all(math.isfinite(number) and number >= 0 for number in numbers),
            self.backoff_factor < 1,
            not self.retry_methods <= IDEMPOTENT_METHODS,
        )
        if any(problems):
            raise ValueError(
                "retry policy needs 1-10 attempts, finite non-negative delays, "
                "a backoff factor of at least 1 and idempotent retry methods"
            )

    def backoff(self, attempt: int) -> float:
        """The computed delay after failed attempt number ``attempt``."""
        delay = min(
            self.max_backoff, self.backoff_base * self.backoff_factor ** (attempt - 1)
        )
        return _RANDOM.uniform(delay / 2, delay) if self.jitter else delay

    def delay_after_response(
        self, request: httpx.Request, response: httpx.Response, attempt: int
    ) -> float | None:
        """Seconds to wait before retrying, or ``None`` to return ``response``."""
        retryable = (
            attempt < self.max_attempts
            and request.method in self.retry_methods
            and response.status_code in self.retry_statuses
        )
        if not retryable:
            return None
        retry_after = parse_retry_after(response.headers.get("retry-after"))
        if retry_after is None:
            return self.backoff(attempt)
        return retry_after if retry_after <= self.max_retry_after else None

    def delay_after_error(
        self, request: httpx.Request, error: httpx.TransportError, attempt: int
    ) -> float | None:
        """Seconds to wait before retrying, or ``None`` to raise."""
        if attempt >= self.max_attempts or is_tls_verification_failure(error):
            return None
        if isinstance(error, _NOT_SENT) or request.method in self.retry_methods:
            return self.backoff(attempt)
        return None
