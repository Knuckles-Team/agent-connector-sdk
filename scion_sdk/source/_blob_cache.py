"""Bounded content-addressed blob cache."""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from scion_sdk.source._client_models import (
    _DEFAULT_CACHE_BYTES,
    _DEFAULT_CACHE_ENTRIES,
    CacheEvent,
)


class BlobCache:
    """Bounded LRU of blob bytes keyed by content digest; reads re-verify."""

    def __init__(
        self,
        *,
        max_entries: int = _DEFAULT_CACHE_ENTRIES,
        max_bytes: int = _DEFAULT_CACHE_BYTES,
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
