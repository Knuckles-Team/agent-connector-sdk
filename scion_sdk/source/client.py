"""One typed client for the served ``source.*`` operations.

The client serves nothing. A connector or host composes it with a transport
that already carries the authenticated caller; admission and path-scope
authorization are enforced by the served operation before a reply arrives.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TypeVar

from pydantic import ValidationError

from scion_sdk.source import _client_models as _m
from scion_sdk.source._blob_cache import BlobCache
from scion_sdk.source._client_channel import _SourceChannel

__all__ = [
    "REFUSAL_REASONS",
    "BlameLine",
    "BlamePage",
    "BlameRequest",
    "BlobCache",
    "BlobPage",
    "BlobRequest",
    "CacheEvent",
    "ChangeEntry",
    "CommitRequest",
    "DiffEntry",
    "DiffPage",
    "DiffRequest",
    "HistoryEntry",
    "HistoryPage",
    "HistoryRequest",
    "LandRequest",
    "PathOutcome",
    "Provenance",
    "Receipt",
    "RevertRequest",
    "SourceClient",
    "SourceRefusal",
    "SourceRefusedError",
    "SourceTransport",
    "TreeEntry",
    "TreePage",
    "TreeRequest",
]

REFUSAL_REASONS = _m.REFUSAL_REASONS
BlameLine = _m.BlameLine
BlamePage = _m.BlamePage
BlameRequest = _m.BlameRequest
BlobPage = _m.BlobPage
BlobRequest = _m.BlobRequest
CacheEvent = _m.CacheEvent
ChangeEntry = _m.ChangeEntry
CommitRequest = _m.CommitRequest
DiffEntry = _m.DiffEntry
DiffPage = _m.DiffPage
DiffRequest = _m.DiffRequest
HistoryEntry = _m.HistoryEntry
HistoryPage = _m.HistoryPage
HistoryRequest = _m.HistoryRequest
LandRequest = _m.LandRequest
PathOutcome = _m.PathOutcome
Provenance = _m.Provenance
Receipt = _m.Receipt
RevertRequest = _m.RevertRequest
SourceRefusal = _m.SourceRefusal
SourceRefusedError = _m.SourceRefusedError
SourceTransport = _m.SourceTransport
TreeEntry = _m.TreeEntry
TreePage = _m.TreePage
TreeRequest = _m.TreeRequest
_Request = _m._Request
_T = TypeVar("_T", bound=_m._Model)
_digest = _m._digest
_DEFAULT_DEADLINE_SECONDS = _m._DEFAULT_DEADLINE_SECONDS
_DEFAULT_CACHE_BYTES = _m._DEFAULT_CACHE_BYTES


class SourceClient:
    """One frozen typed method per served ``source.*`` operation."""

    def __init__(
        self,
        transport: SourceTransport,
        *,
        cache: BlobCache | None = None,
        deadline_seconds: float = _DEFAULT_DEADLINE_SECONDS,
        max_blob_bytes: int = _DEFAULT_CACHE_BYTES,
    ) -> None:
        if deadline_seconds <= 0 or max_blob_bytes < 1:
            raise ValueError("deadline and blob bound must be positive")
        self._channel = _SourceChannel(transport, deadline_seconds)
        self._receipts = self._channel.receipts
        self.cache = cache or BlobCache()
        self._max_blob = max_blob_bytes

    async def tree(self, request: TreeRequest) -> TreePage:
        return await self._page("tree", request, TreePage)

    async def diff(self, request: DiffRequest) -> DiffPage:
        return await self._page("diff", request, DiffPage)

    async def history(self, request: HistoryRequest) -> HistoryPage:
        return await self._page("history", request, HistoryPage)

    async def blame(self, request: BlameRequest) -> BlamePage:
        return await self._page("blame", request, BlamePage)

    async def blob(self, request: BlobRequest) -> BlobPage:
        """Serve cached bytes while the stored digest matches; else read through."""
        payload = request.model_dump(mode="json")
        request_digest = _digest(payload)
        operation_id = f"blob-{request_digest[:32]}"
        if request.digest is not None:
            cached = self.cache.get(request.digest)
            if cached is not None:
                return BlobPage(
                    provenance=Provenance(
                        repository_id=request.repository_id,
                        revision=request.ref,
                        operation_id=operation_id,
                        request_digest=request_digest,
                    ),
                    path=request.path,
                    digest=request.digest,
                    content=cached,
                    cache="hit",
                )
        body = await self._channel.invoke("blob", payload, operation_id)
        try:
            content = base64.b64decode(str(body["content_base64"]), validate=True)
        except (KeyError, ValueError):
            raise self._channel.refusal(
                "transport_unavailable", "blob", operation_id
            ) from None
        if len(content) > self._max_blob:
            raise self._channel.refusal("oversized", "blob", operation_id)
        digest = hashlib.sha256(content).hexdigest()
        if request.digest is not None and digest != request.digest:
            raise self._channel.refusal("conflict", "blob", operation_id)
        self.cache.put(content)
        return BlobPage(
            provenance=Provenance(
                repository_id=request.repository_id,
                revision=str(body.get("revision", request.ref)),
                operation_id=operation_id,
                request_digest=request_digest,
            ),
            path=request.path,
            digest=digest,
            content=content,
            cache="miss",
        )

    async def commit(self, request: CommitRequest) -> Receipt:
        return await self._channel.write("commit", request)

    async def land(self, request: LandRequest) -> Receipt:
        return await self._channel.write("land", request)

    async def revert(self, request: RevertRequest) -> Receipt:
        return await self._channel.write("revert", request)

    async def _page(self, operation: str, request: _Request, model: type[_T]) -> _T:
        payload = request.model_dump(mode="json")
        binding = _digest({k: v for k, v in payload.items() if k != "continuation"})
        operation_id = f"{operation}-{binding[:32]}"
        if request.continuation is not None:
            payload["continuation"] = self._channel.cursor(
                request.continuation, binding, operation, operation_id
            )
        body = await self._channel.invoke(operation, payload, operation_id)
        entries = body.get("entries", body.get("lines", ()))
        if not isinstance(entries, list) or len(entries) > request.page_size:
            raise self._channel.refusal("oversized", operation, operation_id)
        next_cursor = body.get("continuation")
        key = "lines" if operation == "blame" else "entries"
        try:
            return model.model_validate(
                {
                    key: tuple(entries),
                    "continuation": f"{binding[:16]}:{next_cursor}"
                    if next_cursor
                    else None,
                    "provenance": Provenance(
                        repository_id=request.repository_id,
                        revision=str(body.get("revision", request.ref)),
                        operation_id=operation_id,
                        request_digest=binding,
                        page_size=request.page_size,
                    ),
                }
            )
        except ValidationError:
            raise self._channel.refusal(
                "transport_unavailable", operation, operation_id
            ) from None
