"""The attempt loop shared by the synchronous and asynchronous transports.

:func:`attempt_flow` is a generator that performs no I/O. It yields ``None`` when
the driver should send the request (and receives the response or transport
error back) and a :class:`Pause` when the driver should wait before the next
attempt. It returns the final response or raises the mapped error.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from dataclasses import dataclass
from typing import cast

import httpx

from agent_connector_sdk.http.errors import error_for_transport_failure
from agent_connector_sdk.http.redaction import redact_url
from agent_connector_sdk.http.retry import RetryPolicy

__all__ = ["AttemptFlow", "Done", "Outcome", "Pause", "advance", "attempt_flow"]

#: What one attempt produced.
Outcome = httpx.Response | httpx.TransportError


@dataclass(frozen=True)
class Pause:
    """Wait ``seconds``, after closing ``discard`` when it is a response."""

    seconds: float
    discard: httpx.Response | None


@dataclass(frozen=True)
class Done:
    """The flow finished with ``response``."""

    response: httpx.Response


AttemptFlow = Generator[Pause | None, Outcome, httpx.Response]


def advance(flow: AttemptFlow, value: Outcome | None) -> Pause | Done | None:
    """Send ``value`` (``None`` to start or resume after a pause) into ``flow``.

    Completion is returned as :class:`Done` rather than raised as
    ``StopIteration``, which a coroutine may not propagate (PEP 479).
    """
    try:
        return next(flow) if value is None else flow.send(value)
    except StopIteration as stop:
        return Done(cast("httpx.Response", stop.value))


def _log_attempt(
    logger: logging.Logger,
    request: httpx.Request,
    *,
    outcome: Outcome,
    fields: dict[str, object],
) -> None:
    result = (
        outcome.status_code
        if isinstance(outcome, httpx.Response)
        else type(outcome).__name__
    )
    fields.update(method=request.method, url=redact_url(request.url), result=result)
    level = logging.INFO if fields["retry_in"] is None else logging.WARNING
    logger.log(
        level,
        "http %s %s -> %s (attempt %s, %sms)",
        fields["method"],
        fields["url"],
        result,
        fields["attempt"],
        fields["elapsed_ms"],
        extra={"http": fields},
    )


def attempt_flow(
    policy: RetryPolicy, request: httpx.Request, logger: logging.Logger
) -> AttemptFlow:
    """Drive one request through ``policy``, logging every attempt."""
    attempt = 1
    while True:
        started = time.monotonic()
        outcome = yield None
        if isinstance(outcome, httpx.Response):
            delay = policy.delay_after_response(request, outcome, attempt)
        else:
            delay = policy.delay_after_error(request, outcome, attempt)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        fields: dict[str, object] = {
            "attempt": attempt,
            "elapsed_ms": elapsed_ms,
            "retry_in": delay,
        }
        _log_attempt(logger, request, outcome=outcome, fields=fields)
        response = outcome if isinstance(outcome, httpx.Response) else None
        if delay is None and response is not None:
            return response
        if delay is None and isinstance(outcome, httpx.TransportError):
            raise error_for_transport_failure(
                outcome, request, attempts=attempt
            ) from outcome
        yield Pause(delay or 0.0, response)
        attempt += 1
