"""Explicitly retry-safe asynchronous callable execution."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable

import anyio

from agent_connector_sdk.http.retry import RetryPolicy, is_tls_verification_failure

__all__ = ["run_with_resilience"]


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
    if (selected.max_attempts > 1 or fallbacks) and retry_safe is not True:
        raise ValueError("retries and fallbacks require retry-safe operations")
    if len(fallbacks) > 10:
        raise ValueError("at most ten fallbacks are allowed")
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout must be finite and positive")
    if not isinstance(retry_on, tuple) or not all(
        isinstance(item, type) and issubclass(item, Exception) and item is not Exception
        for item in retry_on
    ):
        raise ValueError("retry_on must be a tuple of exception types")

    async def invoke(call: Callable[[], Awaitable[T]]) -> T:
        if timeout_seconds is None:
            return await call()
        with anyio.fail_after(timeout_seconds):
            return await call()

    for attempt in range(1, selected.max_attempts + 1):
        try:
            return await invoke(primary)
        except (TimeoutError, PermissionError, TypeError, ValueError):
            raise
        except retry_on as exc:
            if is_tls_verification_failure(exc):
                raise
            if attempt < selected.max_attempts:
                await anyio.sleep(selected.backoff(attempt))
                continue
            if not fallbacks:
                raise
    for index, fallback in enumerate(fallbacks):
        try:
            return await invoke(fallback)
        except (TimeoutError, PermissionError, TypeError, ValueError):
            raise
        except retry_on as exc:
            if is_tls_verification_failure(exc):
                raise
            if index == len(fallbacks) - 1:
                raise
    raise RuntimeError("resilience policy exhausted without a result")
