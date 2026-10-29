"""The shared per-host request limiter paces calls with a minimum interval."""

from __future__ import annotations

import asyncio
from itertools import pairwise

import pytest

from agent_connector_sdk.httpsupport import RateLimiter as ExportedRateLimiter
from agent_connector_sdk.httpsupport.rate_limit import RateLimiter

pytestmark = [pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R005")]


class FakeClock:
    """A monotonic clock that advances only when the limiter sleeps."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_exported_from_httpsupport() -> None:
    assert ExportedRateLimiter is RateLimiter


async def test_first_call_does_not_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock=clock, sleep=clock.sleep)
    await limiter.wait()
    assert clock.sleeps == []


async def test_rate_respected_with_fake_clock() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock=clock, sleep=clock.sleep)
    await limiter.wait()
    clock.now += 0.5
    await limiter.wait()
    assert clock.sleeps == [pytest.approx(1.5)]
    clock.now += 5.0
    await limiter.wait()
    assert clock.sleeps == [pytest.approx(1.5)]


async def test_concurrent_callers_are_spaced_in_order() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)
    stamps: list[float] = []

    async def call() -> None:
        await limiter.wait()
        stamps.append(clock.now)

    await asyncio.gather(*(call() for _ in range(5)))
    assert stamps == [pytest.approx(100.0 + i) for i in range(5)]
    assert all(b - a >= 1.0 - 1e-9 for a, b in pairwise(stamps))


async def test_async_context_manager_and_real_clock() -> None:
    limiter = RateLimiter(0.05)
    loop = asyncio.get_running_loop()
    start = loop.time()
    async with limiter:
        pass
    async with limiter as entered:
        assert entered is limiter
    assert loop.time() - start >= 0.04


@pytest.mark.parametrize(("given", "expected"), [(-3.0, 0.0), (0, 0.0), (1.5, 1.5)])
async def test_interval_is_clamped_and_zero_never_waits(
    given: float, expected: float
) -> None:
    clock = FakeClock()
    limiter = RateLimiter(given, clock=clock, sleep=clock.sleep)
    assert limiter.min_interval_seconds == expected
    if expected == 0.0:
        await limiter.wait()
        await limiter.wait()
        assert clock.sleeps == []
