"""Explicitly retry-safe callable execution."""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable

import anyio

from agent_connector_sdk.http.retry import RetryPolicy, is_tls_verification_failure

__all__ = ["run_with_resilience", "run_with_resilience_sync"]


def _validate(
    policy: RetryPolicy,
    retry_on: tuple[type[Exception], ...],
    retry_safe: bool,
    fallback_count: int,
) -> None:
    if (policy.max_attempts > 1 or fallback_count) and retry_safe is not True:
        raise ValueError("retries and fallbacks require retry-safe operations")
    if fallback_count > 10:
        raise ValueError("at most ten fallbacks are allowed")
    if not isinstance(retry_on, tuple) or not all(
        isinstance(item, type) and issubclass(item, Exception) and item is not Exception
        for item in retry_on
    ):
        raise ValueError("retry_on must be a tuple of exception types")


def _plan[T](
    primary: Callable[[], T],
    fallbacks: tuple[Callable[[], T], ...],
    policy: RetryPolicy,
) -> list[Callable[[], T]]:
    return [primary] * policy.max_attempts + list(fallbacks)


def _retryable(error: Exception, retry_on: tuple[type[Exception], ...]) -> bool:
    if isinstance(error, (TimeoutError, PermissionError, TypeError, ValueError)):
        return False
    return isinstance(error, retry_on) and not is_tls_verification_failure(error)


async def run_with_resilience[T](
    primary: Callable[[], Awaitable[T]],
    *,
    retry_on: tuple[type[Exception], ...],
    retry_safe: bool,
    policy: RetryPolicy | None = None,
    timeout_seconds: float | None = None,
    fallbacks: tuple[Callable[[], Awaitable[T]], ...] = (),
) -> T:
    """Run an async callable under explicit retry and fallback policy.

    Repeated calls and fallbacks require the caller to affirm they are safe.
    Timeout and cancellation propagate without another call: an interrupted
    operation may already have produced an effect. The timeout is cooperative;
    a coroutine that suppresses cancellation cannot be forcibly stopped.
    """
    selected = policy or RetryPolicy(max_attempts=1)
    _validate(selected, retry_on, retry_safe, len(fallbacks))
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout must be finite and positive")
    calls = _plan(primary, fallbacks, selected)
    for index, call in enumerate(calls):
        if 0 < index < selected.max_attempts:
            await anyio.sleep(selected.backoff(index))
        try:
            if timeout_seconds is None:
                return await call()
            with anyio.fail_after(timeout_seconds):
                return await call()
        except Exception as exc:
            if index == len(calls) - 1 or not _retryable(exc, retry_on):
                raise
    raise RuntimeError("resilience policy exhausted without a result")


def run_with_resilience_sync[T](
    primary: Callable[[], T],
    *,
    retry_on: tuple[type[Exception], ...],
    retry_safe: bool,
    policy: RetryPolicy | None = None,
    timeout_seconds: float | None = None,
    fallbacks: tuple[Callable[[], T], ...] = (),
) -> T:
    """Run a blocking callable without claiming to enforce a timeout.

    Requested timeouts are refused before any call because an arbitrary
    blocking function cannot be stopped safely. Do not call this from an event
    loop; use the async runner for cancellable async operations.
    """
    selected = policy or RetryPolicy(max_attempts=1)
    _validate(selected, retry_on, retry_safe, len(fallbacks))
    if timeout_seconds is not None:
        raise ValueError("timeouts are unavailable for blocking callables")
    calls = _plan(primary, fallbacks, selected)
    for index, call in enumerate(calls):
        if 0 < index < selected.max_attempts:
            time.sleep(selected.backoff(index))
        try:
            return call()
        except Exception as exc:
            if index == len(calls) - 1 or not _retryable(exc, retry_on):
                raise
    raise RuntimeError("resilience policy exhausted without a result")
