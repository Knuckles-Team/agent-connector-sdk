"""Success checks and bounded JSON requests on a governed client."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import JsonValue

from agent_connector_sdk.http.bodies import (
    DEFAULT_MAX_RESPONSE_BYTES,
    aread_bounded,
    read_bounded,
)
from agent_connector_sdk.http.errors import HttpProblemError, error_for_response
from agent_connector_sdk.http.problems import ProblemDetails
from agent_connector_sdk.http.redaction import redact_url

__all__ = [
    "ERROR_BODY_BYTES",
    "aensure_success",
    "arequest_json",
    "ensure_success",
    "request_json",
]

#: How much of an error body is read to look for problem details.
ERROR_BODY_BYTES = 64 * 1024


def _error_body(chunks: list[bytes]) -> bytes:
    return b"".join(chunks)[:ERROR_BODY_BYTES]


def ensure_success(response: httpx.Response) -> None:
    """Raise the problem error for a streamed response with status 400 or above."""
    if response.status_code < 400:
        return
    chunks: list[bytes] = []
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        if sum(map(len, chunks)) >= ERROR_BODY_BYTES:
            break
    error = error_for_response(response, _error_body(chunks))
    if error is not None:
        raise error


async def aensure_success(response: httpx.Response) -> None:
    """The asynchronous form of :func:`ensure_success`."""
    if response.status_code < 400:
        return
    chunks: list[bytes] = []
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        if sum(map(len, chunks)) >= ERROR_BODY_BYTES:
            break
    error = error_for_response(response, _error_body(chunks))
    if error is not None:
        raise error


def _json(response: httpx.Response, body: bytes) -> JsonValue:
    if not body:
        return None
    try:
        document: JsonValue = json.loads(body)
    except ValueError as exc:
        raise HttpProblemError(
            ProblemDetails.sdk(
                "invalid-json",
                "Response is not valid JSON",
                detail=f"{response.request.method} {redact_url(response.request.url)}",
            )
        ) from exc
    return document


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    **kwargs: Any,
) -> JsonValue:
    """Send a request and return its JSON body (``None`` for an empty body).

    ``kwargs`` are passed to ``client.stream`` (``params``, ``json``, ``headers``...).

    Raises:
        HttpProblemError: a status of 400 or above, invalid JSON, or a transport
            failure; ``ResponseTooLargeError`` beyond ``max_bytes``.
    """
    with client.stream(method, url, **kwargs) as response:
        ensure_success(response)
        return _json(response, read_bounded(response, max_bytes))


async def arequest_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    **kwargs: Any,
) -> JsonValue:
    """The asynchronous form of :func:`request_json`."""
    async with client.stream(method, url, **kwargs) as response:
        await aensure_success(response)
        return _json(response, await aread_bounded(response, max_bytes))
