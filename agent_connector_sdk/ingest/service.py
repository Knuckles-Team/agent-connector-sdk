"""Commit typed change sets through an epistemic-graph ingest transport.

Each submission reads the stream's durable checkpoint, builds one generated
``SourceIngestionRequest`` that expects exactly that checkpoint, and commits it.
Submissions for one stream are serialized in this process; a race with another
process re-reads the checkpoint and rebuilds, within a bounded budget.

The transport's client belongs to one event loop. Async callers on any loop and
synchronous callers on any other thread run the commit on that loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Awaitable
from typing import TypeVar

from epistemic_graph.generated.source_ingestion import SourceIngestionReceipt

from agent_connector_sdk.ingest.errors import (
    IngestConflictError,
    IngestError,
    IngestUnavailableError,
)
from agent_connector_sdk.ingest.model import ChangeSet, Entity, IngestBinding
from agent_connector_sdk.ingest.records import media_entity
from agent_connector_sdk.ingest.request import build_request
from agent_connector_sdk.ingest.transport import IngestTransport

__all__ = ["DEFAULT_ATTEMPTS", "DEFAULT_SYNC_TIMEOUT_S", "KnowledgeIngest"]

DEFAULT_ATTEMPTS = 3
DEFAULT_SYNC_TIMEOUT_S = 30.0
_MESSAGE_LIMIT = 300
_T = TypeVar("_T")


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class KnowledgeIngest:
    """The process's knowledge-ingest service over one transport.

    Args:
        transport: The epistemic-graph transport (see
            :class:`~agent_connector_sdk.ingest.transport.EpistemicGraphIngestTransport`).
        loop: The loop the transport's client runs on; ``None`` when the
            transport is used only from its caller's own loop.
        sync_timeout_s: Bound on :meth:`submit_blocking`.
        attempts: Checkpoint-race attempts before ``IngestConflictError``.
    """

    def __init__(
        self,
        transport: IngestTransport,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        sync_timeout_s: float = DEFAULT_SYNC_TIMEOUT_S,
        attempts: int = DEFAULT_ATTEMPTS,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._transport = transport
        self._loop = loop
        self._sync_timeout_s = sync_timeout_s
        self._attempts = attempts
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def submit(
        self, binding: IngestBinding, changes: ChangeSet
    ) -> SourceIngestionReceipt:
        """Commit ``changes`` for ``binding``; the receipt is returned after commit.

        Raises:
            IngestError: the change set is malformed or epistemic-graph refused it.
            IngestConflictError: the checkpoint kept moving.
        """
        call = self._commit(binding, changes)
        loop = self._loop
        if loop is None or loop is _running_loop():
            return await call
        future = asyncio.run_coroutine_threadsafe(call, loop)
        return await asyncio.wrap_future(future)

    def submit_blocking(
        self, binding: IngestBinding, changes: ChangeSet
    ) -> SourceIngestionReceipt:
        """Commit from synchronous code on a thread other than the engine loop's.

        Raises:
            IngestUnavailableError: there is no engine loop to run on, or this
                thread is that loop's own thread.
            IngestError: as :meth:`submit`, or the commit timed out.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            raise IngestUnavailableError("no engine loop a synchronous ingest can use")
        if loop is _running_loop():
            raise IngestUnavailableError(
                "synchronous ingest cannot run on the engine loop's own thread"
            )
        return self._wait(
            asyncio.run_coroutine_threadsafe(self._commit(binding, changes), loop)
        )

    def _wait(
        self, future: concurrent.futures.Future[SourceIngestionReceipt]
    ) -> SourceIngestionReceipt:
        try:
            return future.result(timeout=self._sync_timeout_s)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise IngestError("the change set commit timed out") from exc

    async def _commit(
        self, binding: IngestBinding, changes: ChangeSet
    ) -> SourceIngestionReceipt:
        media = await self._guard(self._store_media(binding, changes))
        key = (binding.connector, binding.stream)
        async with self._locks.setdefault(key, asyncio.Lock()):
            return await self._retrying(binding, changes, media)

    async def _retrying(
        self, binding: IngestBinding, changes: ChangeSet, media: tuple[Entity, ...]
    ) -> SourceIngestionReceipt:
        for _ in range(self._attempts):
            try:
                return await self._attempt(binding, changes, media)
            except IngestConflictError:
                continue
        raise IngestConflictError(
            f"stream {binding.stream!r} checkpoint moved {self._attempts} times"
        )

    async def _attempt(
        self, binding: IngestBinding, changes: ChangeSet, media: tuple[Entity, ...]
    ) -> SourceIngestionReceipt:
        status = await self._guard(
            self._transport.source_status(binding.connector, binding.stream)
        )
        request = build_request(
            binding,
            changes,
            previous=status.accepted_checkpoint,
            extra_entities=media,
        )
        return await self._guard(self._transport.submit(request))

    async def _store_media(
        self, binding: IngestBinding, changes: ChangeSet
    ) -> tuple[Entity, ...]:
        stored = []
        for asset in changes.media:
            if not asset.data:
                raise IngestError("a media asset has no bytes")
            digest = await self._transport.store_blob(asset.data)
            stored.append(media_entity(binding, asset, digest))
        return tuple(stored)

    @staticmethod
    async def _guard(call: Awaitable[_T]) -> _T:
        try:
            return await call
        except IngestError:
            raise
        except Exception as exc:
            detail = (str(exc).splitlines() or [type(exc).__name__])[0]
            raise IngestError(
                "epistemic-graph did not commit the change set: "
                + detail[:_MESSAGE_LIMIT]
            ) from exc
