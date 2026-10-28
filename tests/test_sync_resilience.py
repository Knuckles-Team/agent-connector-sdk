"""Synchronous callable retry and refusal contracts."""

import ssl

import pytest

from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.resilience import run_with_resilience_sync


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R780.11")
def test_sync_retry_and_fallback_order() -> None:
    calls = []

    def primary() -> str:
        calls.append("primary")
        raise ConnectionError("unavailable")

    def fallback() -> str:
        calls.append("fallback")
        return "ok"

    assert (
        run_with_resilience_sync(
            primary,
            retry_on=(ConnectionError,),
            retry_safe=True,
            policy=RetryPolicy(max_attempts=2, backoff_base=0, jitter=False),
            fallbacks=(fallback,),
        )
        == "ok"
    )
    assert calls == ["primary", "primary", "fallback"]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R780.11")
def test_sync_timeout_and_unsafe_retry_refuse_before_call() -> None:
    calls = []

    def primary() -> str:
        calls.append(1)
        return "ok"

    with pytest.raises(ValueError, match="timeouts are unavailable"):
        run_with_resilience_sync(
            primary, retry_on=(OSError,), retry_safe=True, timeout_seconds=1
        )
    with pytest.raises(ValueError, match="retry-safe"):
        run_with_resilience_sync(
            primary,
            retry_on=(OSError,),
            retry_safe=False,
            policy=RetryPolicy(max_attempts=2),
        )
    assert not calls


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R780.11")
@pytest.mark.parametrize(
    "error", [PermissionError(), ssl.SSLCertVerificationError(), TimeoutError()]
)
def test_sync_deterministic_and_timeout_errors_never_retry(error) -> None:
    calls = []

    def primary() -> str:
        calls.append(1)
        raise error

    with pytest.raises(type(error)):
        run_with_resilience_sync(
            primary,
            retry_on=(OSError,),
            retry_safe=True,
            policy=RetryPolicy(max_attempts=2, backoff_base=0, jitter=False),
            fallbacks=(primary,),
        )
    assert calls == [1]
