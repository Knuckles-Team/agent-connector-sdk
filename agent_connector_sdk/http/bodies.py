"""Response bodies read or streamed within a size bound."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx

from agent_connector_sdk.http.errors import ResponseTooLargeError
from agent_connector_sdk.http.problems import ProblemDetails
from agent_connector_sdk.http.redaction import redact_url

__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "aiter_bounded",
    "aread_bounded",
    "iter_bounded",
    "read_bounded",
]

#: Default bound for a response body, in bytes.
DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _too_large(response: httpx.Response, max_bytes: int) -> ResponseTooLargeError:
    return ResponseTooLargeError(
        ProblemDetails.sdk(
            "response-too-large",
            "Response body too large",
            detail=f"{response.request.method} {redact_url(response.request.url)}",
            max_bytes=max_bytes,
        )
    )


def _check_declared_length(response: httpx.Response, max_bytes: int) -> None:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise _too_large(response, max_bytes)


def iter_bounded(response: httpx.Response, max_bytes: int) -> Iterator[bytes]:
    """Yield a streamed body's chunks, raising once more than ``max_bytes`` arrived.

    Raises:
        ResponseTooLargeError: the declared or received length exceeds the bound.
    """
    _check_declared_length(response, max_bytes)
    received = 0
    for chunk in response.iter_bytes():
        received += len(chunk)
        if received > max_bytes:
            raise _too_large(response, max_bytes)
        yield chunk


async def aiter_bounded(
    response: httpx.Response, max_bytes: int
) -> AsyncIterator[bytes]:
    """The asynchronous form of :func:`iter_bounded`."""
    _check_declared_length(response, max_bytes)
    received = 0
    async for chunk in response.aiter_bytes():
        received += len(chunk)
        if received > max_bytes:
            raise _too_large(response, max_bytes)
        yield chunk


def read_bounded(
    response: httpx.Response, max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
) -> bytes:
    """Read a streamed body of at most ``max_bytes``."""
    return b"".join(iter_bounded(response, max_bytes))


async def aread_bounded(
    response: httpx.Response, max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
) -> bytes:
    """Read a streamed body of at most ``max_bytes``."""
    return b"".join([chunk async for chunk in aiter_bounded(response, max_bytes)])
