"""Transports that retry under a :class:`RetryPolicy` and log every attempt."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import cast

import anyio
import httpx

from scion_sdk.http.flow import Done, Outcome, Pause, advance, attempt_flow
from scion_sdk.http.retry import RetryPolicy

__all__ = ["AsyncGovernedTransport", "GovernedTransport"]


def _isolate_cookies(
    request: httpx.Request, response: httpx.Response | None = None
) -> None:
    """Strip cookie state at the governed transport boundary."""
    request.headers.pop("cookie", None)
    if response is not None:
        response.headers.pop("set-cookie", None)


class _GovernedTransportConfig[InnerT, SleepT]:
    """Store settings shared by synchronous and asynchronous transports."""

    def __init__(
        self,
        inner: InnerT,
        *,
        policy: RetryPolicy,
        logger: logging.Logger,
        sleep: SleepT | Callable[[float], None] = time.sleep,
        isolate_cookies: bool = False,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._logger = logger
        self._sleep = cast(SleepT, sleep)
        self._isolate_cookies = isolate_cookies


class GovernedTransport(
    _GovernedTransportConfig[httpx.BaseTransport, Callable[[float], None]],
    httpx.BaseTransport,
):
    """Wraps sync requests with retries, logging and optional cookie isolation."""

    def _send(self, request: httpx.Request) -> Outcome:
        if self._isolate_cookies:
            _isolate_cookies(request)
        try:
            response = self._inner.handle_request(request)
        except httpx.TransportError as error:
            return error
        if self._isolate_cookies:
            _isolate_cookies(request, response)
        return response

    def _pause(self, pause: Pause) -> None:
        if pause.discard is not None:
            pause.discard.close()
        self._sleep(pause.seconds)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Send ``request``, retrying as the policy allows."""
        flow = attempt_flow(self._policy, request, self._logger)
        step = advance(flow, None)
        while not isinstance(step, Done):
            if step is not None:
                self._pause(step)
            step = advance(flow, None if step else self._send(request))
        return step.response

    def close(self) -> None:
        """Close the wrapped transport."""
        self._inner.close()


class AsyncGovernedTransport(
    _GovernedTransportConfig[
        httpx.AsyncBaseTransport, Callable[[float], Awaitable[None]]
    ],
    httpx.AsyncBaseTransport,
):
    """Wraps async requests with retries, logging and optional cookie isolation."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        policy: RetryPolicy,
        logger: logging.Logger,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
        isolate_cookies: bool = False,
    ) -> None:
        super().__init__(
            inner,
            policy=policy,
            logger=logger,
            sleep=sleep,
            isolate_cookies=isolate_cookies,
        )

    async def _outcome(
        self, request: httpx.Request, pause: Pause | None
    ) -> Outcome | None:
        if pause is None:
            if self._isolate_cookies:
                _isolate_cookies(request)
            try:
                response = await self._inner.handle_async_request(request)
            except httpx.TransportError as error:
                return error
            if self._isolate_cookies:
                _isolate_cookies(request, response)
            return response
        if pause.discard is not None:
            await pause.discard.aclose()
        await self._sleep(pause.seconds)
        return None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send ``request``, retrying as the policy allows."""
        step = advance(flow := attempt_flow(self._policy, request, self._logger), None)
        while not isinstance(step, Done):
            step = advance(flow, await self._outcome(request, step))
        return step.response

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self._inner.aclose()
