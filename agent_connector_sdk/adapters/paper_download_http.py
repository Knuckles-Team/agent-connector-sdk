"""Bounded governed HTTP transfer of document bytes."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import TYPE_CHECKING, Any

import anyio
import httpx

from agent_connector_sdk.adapters.paper_document_errors import (
    DocumentRefusal,
    _DocumentRateLimit,
)
from agent_connector_sdk.adapters.paper_provider import ProviderFailure
from agent_connector_sdk.adapters.paper_quota import QuotaSlot
from agent_connector_sdk.http.bodies import aiter_bounded
from agent_connector_sdk.http.client import create_async_http_client
from agent_connector_sdk.http.errors import ResponseTooLargeError
from agent_connector_sdk.http.retry import parse_retry_after

if TYPE_CHECKING:
    from agent_connector_sdk.adapters.paper_download import (
        DocumentAdmission,
        DocumentRequest,
    )


async def _stream(
    request: DocumentRequest, admission: DocumentAdmission, fd: int, *, slot: QuotaSlot
) -> tuple[int, str]:
    async with (
        create_async_http_client(admission.http) as client,
        client.stream(
            "GET", request.offer.url, headers={"Accept-Encoding": "identity"}
        ) as response,
    ):
        return await _receive(response, request, admission=admission, fd=fd, slot=slot)


async def _receive(
    response: httpx.Response,
    request: DocumentRequest,
    *,
    admission: DocumentAdmission,
    fd: int,
    slot: QuotaSlot,
) -> tuple[int, str]:
    declared = _check_response(response, request, admission=admission, slot=slot)
    digest = hashlib.sha256()
    total = await _copy_response(response, admission.max_bytes, fd=fd, digest=digest)
    if total == 0 or (declared is not None and declared != total):
        raise DocumentRefusal("integrity_failed")
    _check_digest(response, digest)
    return total, digest.hexdigest()


async def _copy_response(
    response: httpx.Response, max_bytes: int, *, fd: int, digest: Any
) -> int:
    try:
        return await _copy_chunks(response, max_bytes, fd=fd, digest=digest)
    except ResponseTooLargeError:
        raise DocumentRefusal("size_exceeded") from None
    except httpx.RemoteProtocolError:
        raise DocumentRefusal("integrity_failed") from None
    except OSError:
        raise DocumentRefusal("storage_denied") from None


async def _copy_chunks(
    response: httpx.Response, max_bytes: int, *, fd: int, digest: Any
) -> int:
    total = 0
    async for chunk in aiter_bounded(response, max_bytes):
        total += len(chunk)
        digest.update(chunk)
        worker_fd = os.dup(fd)
        await anyio.to_thread.run_sync(
            _write_chunk, worker_fd, chunk, abandon_on_cancel=True
        )
    return total


def _check_response(
    response: httpx.Response,
    request: DocumentRequest,
    *,
    admission: DocumentAdmission,
    slot: QuotaSlot,
) -> int | None:
    _check_status(response, slot)
    if response.headers.get("content-encoding", "identity").lower() not in {
        "",
        "identity",
    }:
        raise DocumentRefusal("unsupported_media")
    media = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
    if media != request.offer.media_type:
        raise DocumentRefusal("unsupported_media")
    declared = response.headers.get("content-length")
    if declared is not None and (
        not declared.isdecimal() or int(declared) > admission.max_bytes
    ):
        raise DocumentRefusal("size_exceeded")
    return int(declared) if declared is not None else None


def _check_status(response: httpx.Response, slot: QuotaSlot) -> None:
    if response.status_code == 429:
        slot.retain()
        try:
            retry_after = parse_retry_after(response.headers.get("retry-after"))
            ProviderFailure("rate_limited", retry_after_seconds=retry_after)
        except (ValueError, OverflowError):
            retry_after = None
        raise _DocumentRateLimit(retry_after)
    if response.status_code in {401, 403}:
        raise DocumentRefusal("unauthorized")
    if response.status_code != 200:
        raise DocumentRefusal("document_unavailable")


def _check_digest(response: httpx.Response, digest: Any) -> None:
    advertised = response.headers.get("digest")
    if advertised is not None:
        try:
            algorithm, value = advertised.split("=", 1)
            expected = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise DocumentRefusal("integrity_failed") from None
        if algorithm.strip().lower() != "sha-256" or expected != digest.digest():
            raise DocumentRefusal("integrity_failed")
    if "content-md5" in response.headers:
        raise DocumentRefusal("integrity_failed")


def _write_chunk(fd: int, chunk: bytes) -> None:
    try:
        _write_all(fd, chunk)
    finally:
        os.close(fd)


def _write_all(fd: int, chunk: bytes) -> None:
    remaining = memoryview(chunk)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("document write made no progress")
        remaining = remaining[written:]
