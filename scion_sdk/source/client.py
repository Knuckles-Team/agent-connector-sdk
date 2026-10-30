"""One typed client for the served ``source.*`` operations.

The client serves nothing. A connector or host composes it with a transport
that already carries the authenticated caller; admission and path-scope
authorization are enforced by the served operation before a reply arrives.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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

RefusalReason = Literal[
    "unauthorized",
    "not_found",
    "conflict",
    "path_denied",
    "oversized",
    "deadline_exceeded",
    "transport_unavailable",
]
REFUSAL_REASONS: tuple[str, ...] = (
    "unauthorized",
    "not_found",
    "conflict",
    "path_denied",
    "oversized",
    "deadline_exceeded",
    "transport_unavailable",
)
_DIGEST = r"^[0-9a-f]{64}$"
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 1000
DEFAULT_CACHE_ENTRIES = 256
DEFAULT_CACHE_BYTES = 16 * 1024 * 1024
DEFAULT_DEADLINE_SECONDS = 30.0


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _Request(_Model):
    repository_id: str = Field(min_length=1, max_length=256)
    ref: str = Field(min_length=1, max_length=256)
    path_prefix: str | None = Field(default=None, max_length=1024)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    continuation: str | None = None


class TreeRequest(_Request):
    pass


class BlobRequest(_Model):
    repository_id: str = Field(min_length=1, max_length=256)
    ref: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=1024)
    digest: str | None = Field(default=None, pattern=_DIGEST)


class DiffRequest(_Request):
    base_ref: str = Field(min_length=1, max_length=256)


class HistoryRequest(_Request):
    pass


class BlameRequest(_Request):
    path: str = Field(min_length=1, max_length=1024)


class ChangeEntry(_Model):
    path: str = Field(min_length=1, max_length=1024)
    operation: Literal["put", "delete"]
    blob_digest: str | None = Field(default=None, pattern=_DIGEST)
    content_base64: str | None = None


class CommitRequest(_Model):
    repository_id: str = Field(min_length=1, max_length=256)
    branch: str = Field(min_length=1, max_length=256)
    base_revision: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=4096)
    changes: tuple[ChangeEntry, ...] = Field(min_length=1, max_length=MAX_PAGE_SIZE)
    change_id: str | None = Field(default=None, min_length=1, max_length=256)


class LandRequest(_Model):
    repository_id: str = Field(min_length=1, max_length=256)
    branch: str = Field(min_length=1, max_length=256)
    target: str = Field(min_length=1, max_length=256)
    change_id: str | None = Field(default=None, min_length=1, max_length=256)


class RevertRequest(_Model):
    repository_id: str = Field(min_length=1, max_length=256)
    branch: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=256)
    change_id: str | None = Field(default=None, min_length=1, max_length=256)


class Provenance(_Model):
    repository_id: str
    revision: str
    operation_id: str
    request_digest: str
    page_size: int | None = None
    receipt_ref: str | None = None


class TreeEntry(_Model):
    path: str
    mode: str
    digest: str
    size: int = Field(ge=0)


class DiffEntry(_Model):
    path: str
    change: Literal["added", "modified", "deleted"]
    digest: str | None = None


class HistoryEntry(_Model):
    revision: str
    summary: str
    author: str


class BlameLine(_Model):
    line: int = Field(ge=1)
    revision: str
    author: str


class _Page(_Model):
    provenance: Provenance
    continuation: str | None = None


class TreePage(_Page):
    entries: tuple[TreeEntry, ...]


class DiffPage(_Page):
    entries: tuple[DiffEntry, ...]


class HistoryPage(_Page):
    entries: tuple[HistoryEntry, ...]


class BlamePage(_Page):
    lines: tuple[BlameLine, ...]


class BlobPage(_Model):
    provenance: Provenance
    path: str
    digest: str
    content: bytes
    cache: Literal["hit", "miss"]


class PathOutcome(_Model):
    path: str
    outcome: Literal["applied", "unchanged"]


class Receipt(_Model):
    provenance: Provenance
    revision: str
    outcomes: tuple[PathOutcome, ...] = ()


class SourceRefusal(_Model):
    reason: RefusalReason
    operation: str
    operation_id: str


class SourceRefusedError(RuntimeError):
    """A refused or failed operation; carries the typed refusal and no effect."""

    def __init__(self, refusal: SourceRefusal) -> None:
        super().__init__(f"{refusal.operation} refused: {refusal.reason}")
        self.refusal = refusal

    @property
    def reason(self) -> str:
        return self.refusal.reason


class SourceTransport(Protocol):
    """Reaches the served ``source.<operation>`` for the authenticated caller.

    Returns ``{"status": "ok", "result": {...}}`` or
    ``{"status": "refused", "reason": <code>}``. Any raised error maps to
    ``transport_unavailable``.
    """

    async def call(
        self, operation: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Invoke one served source operation."""
        ...


class CacheEvent(_Model):
    event: Literal["hit", "miss", "evict", "mismatch"]
    digest: str
    evictions: int = 0


class BlobCache:
    """Bounded LRU of blob bytes keyed by content digest; reads re-verify."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_CACHE_ENTRIES,
        max_bytes: int = DEFAULT_CACHE_BYTES,
    ) -> None:
        if max_entries < 1 or max_bytes < 1:
            raise ValueError("cache bounds must be positive")
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._items: OrderedDict[str, bytes] = OrderedDict()
        self._bytes = 0
        self.events: list[CacheEvent] = []

    def __len__(self) -> int:
        return len(self._items)

    @property
    def size_bytes(self) -> int:
        return self._bytes

    def get(self, digest: str) -> bytes | None:
        data = self._items.get(digest)
        if data is None:
            self.events.append(CacheEvent(event="miss", digest=digest))
            return None
        if hashlib.sha256(data).hexdigest() != digest:
            self._drop(digest)
            self.events.append(CacheEvent(event="mismatch", digest=digest, evictions=1))
            return None
        self._items.move_to_end(digest)
        self.events.append(CacheEvent(event="hit", digest=digest))
        return data

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        if len(data) > self.max_bytes:
            return digest
        if digest in self._items:
            self._items.move_to_end(digest)
            return digest
        self._items[digest] = data
        self._bytes += len(data)
        evicted = 0
        while len(self._items) > self.max_entries or self._bytes > self.max_bytes:
            oldest = next(iter(self._items))
            self._drop(oldest)
            evicted += 1
        if evicted:
            self.events.append(
                CacheEvent(event="evict", digest=digest, evictions=evicted)
            )
        return digest

    def _drop(self, digest: str) -> None:
        self._bytes -= len(self._items.pop(digest, b""))


_T = TypeVar("_T", bound=_Model)


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SourceClient:
    """One frozen typed method per served ``source.*`` operation."""

    def __init__(
        self,
        transport: SourceTransport,
        *,
        cache: BlobCache | None = None,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        max_blob_bytes: int = DEFAULT_CACHE_BYTES,
    ) -> None:
        if deadline_seconds <= 0 or max_blob_bytes < 1:
            raise ValueError("deadline and blob bound must be positive")
        self._transport = transport
        self.cache = cache or BlobCache()
        self._deadline = deadline_seconds
        self._max_blob = max_blob_bytes
        self._receipts: dict[str, Receipt] = {}

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
        body = await self._invoke("blob", payload, operation_id)
        try:
            content = base64.b64decode(str(body["content_base64"]), validate=True)
        except (KeyError, ValueError):
            raise self._refusal("transport_unavailable", "blob", operation_id) from None
        if len(content) > self._max_blob:
            raise self._refusal("oversized", "blob", operation_id)
        digest = hashlib.sha256(content).hexdigest()
        if request.digest is not None and digest != request.digest:
            raise self._refusal("conflict", "blob", operation_id)
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
        return await self._write("commit", request)

    async def land(self, request: LandRequest) -> Receipt:
        return await self._write("land", request)

    async def revert(self, request: RevertRequest) -> Receipt:
        return await self._write("revert", request)

    def _cursor(
        self, continuation: str, binding: str, operation: str, operation_id: str
    ) -> str:
        prefix, _, cursor = continuation.partition(":")
        if prefix != binding[:16] or not cursor:
            raise self._refusal("conflict", operation, operation_id)
        return cursor

    async def _page(self, operation: str, request: _Request, model: type[_T]) -> _T:
        payload = request.model_dump(mode="json")
        binding = _digest({k: v for k, v in payload.items() if k != "continuation"})
        operation_id = f"{operation}-{binding[:32]}"
        if request.continuation is not None:
            payload["continuation"] = self._cursor(
                request.continuation, binding, operation, operation_id
            )
        body = await self._invoke(operation, payload, operation_id)
        entries = body.get("entries", body.get("lines", ()))
        if not isinstance(entries, list) or len(entries) > request.page_size:
            raise self._refusal("oversized", operation, operation_id)
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
            raise self._refusal(
                "transport_unavailable", operation, operation_id
            ) from None

    async def _write(self, operation: str, request: _Model) -> Receipt:
        payload = request.model_dump(mode="json")
        change_id = payload.pop("change_id", None)
        request_digest = _digest(payload)
        identity = change_id or request_digest[:32]
        operation_id = f"{operation}-{identity}"
        known = self._receipts.get(operation_id)
        if known is not None:
            if known.provenance.request_digest != request_digest:
                raise self._refusal("conflict", operation, operation_id)
            return known
        body = await self._invoke(
            operation, {**payload, "operation_id": operation_id}, operation_id
        )
        try:
            receipt = Receipt(
                provenance=Provenance(
                    repository_id=str(payload["repository_id"]),
                    revision=str(body["revision"]),
                    operation_id=operation_id,
                    request_digest=request_digest,
                    receipt_ref=str(body.get("receipt_ref") or "") or None,
                ),
                revision=str(body["revision"]),
                outcomes=tuple(PathOutcome(**o) for o in body.get("outcomes", ())),
            )
        except (KeyError, TypeError, ValidationError):
            raise self._refusal(
                "transport_unavailable", operation, operation_id
            ) from None
        self._receipts[operation_id] = receipt
        return receipt

    async def _invoke(
        self, operation: str, payload: Mapping[str, Any], operation_id: str
    ) -> Mapping[str, Any]:
        try:
            reply = await asyncio.wait_for(
                self._transport.call(operation, payload), self._deadline
            )
        except TimeoutError:
            raise self._refusal("deadline_exceeded", operation, operation_id) from None
        except Exception:
            raise self._refusal(
                "transport_unavailable", operation, operation_id
            ) from None
        if not isinstance(reply, Mapping):
            raise self._refusal("transport_unavailable", operation, operation_id)
        if reply.get("status") == "refused":
            reason = reply.get("reason")
            if reason not in REFUSAL_REASONS:
                reason = "transport_unavailable"
            raise self._refusal(str(reason), operation, operation_id)
        result = reply.get("result")
        if reply.get("status") != "ok" or not isinstance(result, Mapping):
            raise self._refusal("transport_unavailable", operation, operation_id)
        return result

    @staticmethod
    def _refusal(reason: str, operation: str, operation_id: str) -> SourceRefusedError:
        return SourceRefusedError(
            SourceRefusal(
                reason=reason,  # type: ignore[arg-type]
                operation=operation,
                operation_id=operation_id,
            )
        )
