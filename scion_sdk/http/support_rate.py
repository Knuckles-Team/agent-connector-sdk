"""Rate-limit header parsing, 429 backoff and secret redaction for the API client."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from scion_sdk.http.retry import parse_retry_after

REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class RateLimitSnapshot:
    """The rate-limit headers observed on one response."""

    limit: int | None
    remaining: int | None
    reset: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _header_number(headers: Mapping[str, str], *names: str) -> float | None:
    for name in names:
        value = headers.get(name)
        if value is None:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def _rate_limit(headers: Mapping[str, str]) -> RateLimitSnapshot | None:
    limit = _header_number(headers, "X-RateLimit-Limit", "X-Rate-Limit-Limit")
    remaining = _header_number(
        headers, "X-RateLimit-Remaining", "X-Rate-Limit-Remaining"
    )
    reset = _header_number(headers, "X-RateLimit-Reset", "X-Rate-Limit-Reset")
    if limit is None and remaining is None and reset is None:
        return None
    return RateLimitSnapshot(
        limit=int(limit) if limit is not None else None,
        remaining=int(remaining) if remaining is not None else None,
        reset=reset,
    )


def _backoff_seconds(headers: Mapping[str, str], cap: float) -> float:
    delay = parse_retry_after(headers.get("Retry-After"))
    if delay is None:
        reset = _header_number(headers, "X-Rate-Limit-Reset", "X-RateLimit-Reset")
        if reset is not None:
            delay = max(0.0, reset - time.time()) if reset > 1e9 else reset
    return min(max(delay if delay is not None else 1.0, 0.0), cap)


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text
