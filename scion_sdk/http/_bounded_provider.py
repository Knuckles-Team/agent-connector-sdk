"""Shared egress and size policy for host-admitted source providers."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from scion_sdk.http.client import create_async_http_client
from scion_sdk.http.options import HttpClientOptions


class _BoundedProvider[T: str]:
    def __init__(
        self,
        *,
        provider: T,
        http: HttpClientOptions,
        quota: Callable[[T], AbstractAsyncContextManager[Any]],
        max_bytes: int,
    ) -> None:
        if not http.pin_egress or http.retry.max_attempts != 1 or max_bytes < 1:
            raise ValueError("invalid bounded provider policy")
        self.provider = provider
        self.http = http
        self.quota = quota
        self.max_bytes = max_bytes


async def _bounded(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    result = bytearray()
    async for chunk in chunks:
        if len(result) + len(chunk) > limit:
            raise ValueError("provider response exceeds admitted byte bound")
        result.extend(chunk)
    return bytes(result)


async def _fetch(http: HttpClientOptions, path: str, max_bytes: int) -> bytes:
    async with (
        create_async_http_client(http) as client,
        client.stream("GET", path) as response,
    ):
        response.raise_for_status()
        return await _bounded(response.aiter_bytes(), max_bytes)
