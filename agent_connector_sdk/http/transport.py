"""Transports that retry under a :class:`RetryPolicy` and log every attempt."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

import anyio
import httpx

from agent_connector_sdk.http.flow import Done, Outcome, Pause, advance, attempt_flow
from agent_connector_sdk.http.retry import RetryPolicy

__all__ = ["AsyncGovernedTransport", "GovernedTransport"]


class GovernedTransport(httpx.BaseTransport):
    """Wraps a synchronous transport with retries and request logging."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        policy: RetryPolicy,
        logger: logging.Logger,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._logger = logger
        self._sleep = sleep

    def _send(self, request: httpx.Request) -> Outcome:
        try:
            return self._inner.handle_request(request)
        except httpx.TransportError as error:
            return error

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


class AsyncGovernedTransport(httpx.AsyncBaseTransport):
    """Wraps an asynchronous transport with retries and request logging."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        policy: RetryPolicy,
        logger: logging.Logger,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._logger = logger
        self._sleep = sleep

    async def _outcome(
        self, request: httpx.Request, pause: Pause | None
    ) -> Outcome | None:
        if pause is None:
            try:
                return await self._inner.handle_async_request(request)
            except httpx.TransportError as error:
                return error
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
