"""Typed requests, replies and errors of the served ``source.*`` operations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

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
_DEFAULT_PAGE_SIZE = 200
_MAX_PAGE_SIZE = 1000
_DEFAULT_CACHE_ENTRIES = 256
_DEFAULT_CACHE_BYTES = 16 * 1024 * 1024
_DEFAULT_DEADLINE_SECONDS = 30.0


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _Request(_Model):
    repository_id: str = Field(min_length=1, max_length=256)
    ref: str = Field(min_length=1, max_length=256)
    path_prefix: str | None = Field(default=None, max_length=1024)
    page_size: int = Field(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE)
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
    changes: tuple[ChangeEntry, ...] = Field(min_length=1, max_length=_MAX_PAGE_SIZE)
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


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


_T = TypeVar("_T", bound=_Model)
