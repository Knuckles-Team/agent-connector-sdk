"""Short-lived overlap guard for one durable connector instance."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from epistemic_graph.generated.write_back import SourceChangeSet

from agent_connector_sdk.writeback.errors import WriteBackError


class _InFlight:
    def __init__(self) -> None:
        self._keys: set[tuple[str, str]] = set()
        self._lock = Lock()

    @contextmanager
    def claim(self, change_set: SourceChangeSet) -> Iterator[None]:
        key = (change_set.tenant_id, change_set.idempotency_key)
        with self._lock:
            if key in self._keys:
                raise WriteBackError("write-back operation is already in flight")
            self._keys.add(key)
        try:
            yield
        finally:
            with self._lock:
                self._keys.remove(key)
