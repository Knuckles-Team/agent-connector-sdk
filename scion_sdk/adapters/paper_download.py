"""Host-authorized, quota-governed bounded paper document transfer.

The host supplies tenant authorization, a storage root, and governed HTTP
options. This module does not derive any of these from an MCP request.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import anyio
from pydantic import BaseModel, ConfigDict

from scion_sdk.adapters.paper_document_errors import (
    DocumentRefusal,
    _DocumentRateLimit,
    _translate_download,
)
from scion_sdk.adapters.paper_download_files import (
    _validate,
    _verify_existing,
)
from scion_sdk.adapters.paper_download_http import _stream
from scion_sdk.adapters.paper_download_temp import (
    _open_validation,
    _temporary,
)
from scion_sdk.adapters.paper_models import (
    DocumentOffer,
    DocumentReceipt,
    Identity,
)
from scion_sdk.adapters.paper_provider import ProviderFailure
from scion_sdk.adapters.paper_quota import (
    PaperQuotaPolicy,
    QuotaSlot,
    SharedPaperQuota,
)
from scion_sdk.adapters.paper_search_attempt import _rate_limit
from scion_sdk.adapters.safe_dir import SafeDir
from scion_sdk.http.options import HttpClientOptions

__all__ = [
    "DocumentAdmission",
    "DocumentRefusal",
    "DocumentRequest",
    "PaperDocumentService",
]


class DocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tenant: Identity
    paper_id: Identity
    revision: Identity | None
    offer: DocumentOffer


@dataclass(frozen=True)
class DocumentAdmission:
    root: Path
    http: HttpClientOptions
    quota: PaperQuotaPolicy
    max_bytes: int = 50 * 1024 * 1024
    deadline_seconds: float = 30.0


class PaperDocumentService:
    """Download only after host authorization and quota admission."""

    def __init__(
        self,
        quota: SharedPaperQuota,
        authorize: Callable[
            [DocumentRequest, Any], Awaitable[DocumentAdmission | None]
        ],
    ) -> None:
        self._quota = quota
        self._authorize = authorize

    async def download(self, request: DocumentRequest, context: Any) -> DocumentReceipt:
        try:
            request = DocumentRequest.model_validate(request.model_dump())
        except ValueError:
            raise DocumentRefusal("invalid_query") from None
        try:
            admission = await self._authorize(request, context)
        except Exception:
            raise DocumentRefusal("unauthorized") from None
        admission = _validate_admission(request, admission)
        return await _translate_download(
            _bounded_download(request, admission, self._quota)
        )


def _validate_admission(
    request: DocumentRequest, admission: DocumentAdmission | None
) -> DocumentAdmission:
    if admission is None:
        raise DocumentRefusal("unauthorized")
    if (
        admission.quota.provider_id != request.offer.provider_id
        or not admission.http.pin_egress
        or admission.http.retry.max_attempts != 1
    ):
        raise DocumentRefusal("unauthorized")
    if (
        admission.max_bytes < 1
        or admission.max_bytes > 2**31
        or not 0 < admission.deadline_seconds <= 3600
    ):
        raise DocumentRefusal("unauthorized")
    if _origin(admission.http.base_url) != _origin(request.offer.url):
        raise DocumentRefusal("egress_denied")
    return admission


async def _bounded_download(
    request: DocumentRequest, admission: DocumentAdmission, quota: SharedPaperQuota
) -> DocumentReceipt:
    with anyio.fail_after(admission.deadline_seconds):
        deadline = anyio.current_time() + admission.deadline_seconds
        async with quota.request_slot(admission.quota) as slot:
            return await _retry_download(
                request, admission, slot=slot, deadline=deadline
            )


async def _retry_download(
    request: DocumentRequest,
    admission: DocumentAdmission,
    *,
    slot: QuotaSlot,
    deadline: float,
) -> DocumentReceipt:
    for attempt in range(3):
        try:
            return await _download(request, admission, slot)
        except _DocumentRateLimit as error:
            failure = error
        delay = await _rate_limit(
            ProviderFailure("rate_limited", retry_after_seconds=failure.retry_after),
            slot,
            deadline=deadline,
            spacing=admission.quota.minimum_spacing_ns / 1_000_000_000,
        )
        if delay is not None or attempt == 2:
            raise DocumentRefusal("rate_limited") from None
    raise AssertionError("unreachable")


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port


async def _download(
    request: DocumentRequest, admission: DocumentAdmission, slot: QuotaSlot
) -> DocumentReceipt:
    with _temporary(admission.root) as (directory, name, fd):
        return await _save(
            request, admission, directory=directory, name=name, fd=fd, slot=slot
        )


async def _save(
    request: DocumentRequest,
    admission: DocumentAdmission,
    *,
    directory: SafeDir,
    name: str,
    fd: int,
    slot: QuotaSlot,
) -> DocumentReceipt:
    size, digest = await _stream(request, admission, fd, slot=slot)
    validation_fd = _open_validation(directory, name)
    await anyio.to_thread.run_sync(
        _validate, validation_fd, request.offer.media_type, abandon_on_cancel=True
    )
    artifact = digest + (
        ".pdf" if request.offer.media_type == "application/pdf" else ".html"
    )
    await _install(directory, name, artifact=artifact, digest=digest, size=size)
    parsed = urlsplit(request.offer.url)
    return DocumentReceipt(
        tenant=request.tenant,
        paper_id=request.paper_id,
        revision=request.revision,
        source_url=urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")),
        media_type=request.offer.media_type,
        byte_count=size,
        sha256=digest,
        artifact_ref=artifact,
    )


async def _install(
    directory: SafeDir, name: str, *, artifact: str, digest: str, size: int
) -> None:
    try:
        directory.link(name, artifact)
    except FileExistsError:
        worker_dir = directory.dup()
        await anyio.to_thread.run_sync(
            partial(_verify_existing, worker_dir, artifact, digest=digest, size=size),
            abandon_on_cancel=True,
        )
    except OSError:
        raise DocumentRefusal("storage_denied") from None
