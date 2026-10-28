"""Bounded transient cache owned by one tool request.

The caller must supply an admission policy that rejects credentials, approvals,
and effect results. Authenticated context binding is the caller's responsibility.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

from agent_connector_sdk.mcp.context import ToolExecutionContext

__all__ = ["DEFAULT_REQUEST_CACHE_ENTRIES", "RequestCache", "RequestCacheKey"]

DEFAULT_REQUEST_CACHE_ENTRIES = 128


@dataclass(frozen=True, slots=True)
class RequestCacheKey:
    """Digests of normalized arguments and authorization scope."""

    argument_digest: str
    scope_digest: str

    def __post_init__(self) -> None:
        for digest in (self.argument_digest, self.scope_digest):
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise ValueError("cache key must carry lowercase SHA-256 digests")


class RequestCache[T]:
    """Store caller-admitted transient values until the request ends."""

    def __init__(
        self,
        context: ToolExecutionContext,
        admit: Callable[[T], bool],
        *,
        max_entries: int = DEFAULT_REQUEST_CACHE_ENTRIES,
    ) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise ValueError("invalid request cache size")
        if not 1 <= max_entries <= DEFAULT_REQUEST_CACHE_ENTRIES:
            raise ValueError("invalid request cache size")
        self._context = context
        self._admit = admit
        self._max_entries = max_entries
        self._entries: OrderedDict[RequestCacheKey, T] = OrderedDict()
        self._lock = RLock()
        self._closed = False

    def _check_live(self) -> None:
        if self._closed:
            raise ValueError("request cache is closed")
        if datetime.now(UTC) >= self._context.deadline:
            self._entries.clear()
            self._closed = True
            raise TimeoutError("request cache deadline exceeded")

    def get(self, key: RequestCacheKey) -> T | None:
        """Return a cached value, or None when the key is absent."""
        with self._lock:
            self._check_live()
            if not isinstance(key, RequestCacheKey):
                raise ValueError("cache key must carry digests")
            value = self._entries.get(key)
            if key in self._entries:
                self._entries.move_to_end(key)
            return value

    def put(self, key: RequestCacheKey, value: T) -> None:
        """Store an admitted value, evicting the least recently used entry."""
        with self._lock:
            self._check_live()
            if not isinstance(key, RequestCacheKey):
                raise ValueError("cache key must carry digests")
            if value is None or not self._admit(value):
                raise ValueError("transient value was not admitted")
            self._check_live()
            self._entries[key] = value
            self._entries.move_to_end(key)
            if len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def close(self) -> None:
        """Clear transient values and refuse further access."""
        with self._lock:
            self._entries.clear()
            self._closed = True
