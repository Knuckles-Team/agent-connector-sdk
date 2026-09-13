"""Progress notifications and the HTTP client conformance kit."""

from __future__ import annotations

import logging

import httpx
import pytest

from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.progress import ctx_progress
from agent_connector_sdk.testing.http_clients import (
    HttpClientFactory,
    check_finite_timeout,
    check_problem_mapping,
    check_rate_limit_retry,
    check_secret_redaction,
    check_tls_verification,
    run_http_client_suite,
)
from agent_connector_sdk.testing.results import ConformanceFailure, assert_conformant


class _Context:
    def __init__(self, fail: bool = False) -> None:
        self.reports: list[tuple[float, float | None, str | None]] = []
        self.fail = fail

    async def report_progress(
        self, progress: float, total: float | None, message: str | None
    ) -> None:
        if self.fail:
            raise RuntimeError("client went away")
        self.reports.append((progress, total, message))


async def test_ctx_progress(caplog: pytest.LogCaptureFixture) -> None:
    await ctx_progress(None, 5)
    context = _Context()
    await ctx_progress(context, 2, 4, message="page 2")
    await ctx_progress(context, 7, None)
    assert context.reports == [(2, 4, "page 2"), (7, None, None)]
    for progress, total in ((-1, 10), (11, 10), (1, 0), (float("nan"), 10)):
        with pytest.raises(ValueError):
            await ctx_progress(context, progress, total)
    caplog.set_level(logging.WARNING)
    await ctx_progress(_Context(fail=True), 1)
    assert "client went away" in caplog.text


def _governed(base_url: str) -> httpx.Client:
    options = HttpClientOptions(base_url=base_url, retry=RetryPolicy(backoff_base=0.01))
    return create_http_client(options)


def test_governed_client_is_conformant() -> None:
    factory: HttpClientFactory = _governed
    assert_conformant(run_http_client_suite(factory))


def test_kit_detects_an_ungoverned_client() -> None:
    def plain(base_url: str) -> httpx.Client:
        return httpx.Client(base_url=base_url, timeout=None)

    failed = {
        result.check
        for result in (
            check_finite_timeout(plain),
            check_rate_limit_retry(plain),
            check_secret_redaction(plain),
            check_tls_verification(plain),
        )
        if not result.passed
    }
    assert failed == {
        "finite-timeout",
        "rate-limit-retry",
        "secret-redaction",
        "tls-verification",
    }
    assert check_problem_mapping(_governed).passed
    with pytest.raises(ConformanceFailure):
        assert_conformant([check_finite_timeout(plain)])
