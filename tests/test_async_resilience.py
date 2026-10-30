"""Async callable retry and fallback contract."""

import asyncio

import anyio
import pytest

from scion_sdk.http.retry import RetryPolicy
from scion_sdk.resilience import run_with_resilience


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.10")
async def test_retry_then_fallback_in_order() -> None:
    calls: list[str] = []

    async def primary() -> str:
        calls.append("primary")
        raise OSError("unavailable")

    async def first() -> str:
        calls.append("first")
        raise OSError("unavailable")

    async def second() -> str:
        calls.append("second")
        return "ok"

    result = await run_with_resilience(
        primary,
        retry_on=(OSError,),
        retry_safe=True,
        policy=RetryPolicy(max_attempts=2, backoff_base=0, jitter=False),
        fallbacks=(first, second),
    )
    assert result == "ok"
    assert calls == ["primary", "primary", "first", "second"]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.10")
async def test_refusals_and_timeout_never_retry() -> None:
    calls: list[str] = []

    async def primary() -> str:
        calls.append("primary")
        await anyio.sleep(1)
        return "late"

    policy = RetryPolicy(max_attempts=2, backoff_base=0, jitter=False)
    with pytest.raises(ValueError, match="retry-safe"):
        await run_with_resilience(
            primary, retry_on=(OSError,), retry_safe=False, policy=policy
        )
    assert not calls
    with pytest.raises(TimeoutError):
        await run_with_resilience(
            primary,
            retry_on=(OSError,),
            retry_safe=True,
            policy=policy,
            timeout_seconds=0.001,
            fallbacks=(primary,),
        )
    assert calls == ["primary"]

    async def cancelled() -> str:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_with_resilience(
            cancelled, retry_on=(OSError,), retry_safe=True, policy=policy
        )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.10")
async def test_unlisted_error_never_runs_fallback() -> None:
    calls = []

    async def primary() -> str:
        raise PermissionError("refused")

    async def fallback() -> str:
        calls.append("fallback")
        return "unsafe"

    with pytest.raises(PermissionError):
        await run_with_resilience(
            primary, retry_on=(OSError,), retry_safe=True, fallbacks=(fallback,)
        )
    assert calls == []


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.10")
async def test_invalid_policy_refuses_before_call() -> None:
    calls = []

    async def primary() -> str:
        calls.append(1)
        return "ok"

    with pytest.raises(ValueError, match="retry_on"):
        await run_with_resilience(primary, retry_on=(Exception,), retry_safe=True)
    with pytest.raises(ValueError, match="timeout"):
        await run_with_resilience(
            primary, retry_on=(OSError,), retry_safe=True, timeout_seconds=float("nan")
        )
    assert not calls


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.10")
async def test_certificate_verification_failure_never_retries() -> None:
    import ssl

    calls = []

    async def primary() -> str:
        calls.append(1)
        raise ssl.SSLCertVerificationError("bad certificate")

    with pytest.raises(ssl.SSLCertVerificationError):
        await run_with_resilience(
            primary,
            retry_on=(OSError,),
            retry_safe=True,
            policy=RetryPolicy(max_attempts=2, backoff_base=0, jitter=False),
            fallbacks=(primary,),
        )
    assert calls == [1]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R780.10")
async def test_last_retryable_fallback_failure_propagates() -> None:
    calls = []

    async def primary() -> str:
        calls.append("primary")
        raise ConnectionError("primary")

    async def fallback() -> str:
        calls.append("fallback")
        raise ConnectionError("fallback")

    with pytest.raises(ConnectionError, match="fallback"):
        await run_with_resilience(
            primary, retry_on=(ConnectionError,), retry_safe=True, fallbacks=(fallback,)
        )
    assert calls == ["primary", "fallback"]
