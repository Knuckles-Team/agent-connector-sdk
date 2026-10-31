"""Mapped-result commits and cursor paging of a source stream."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.mapping import Mapped, apply_mapper
from scion_sdk.ingest.model import ChangeSet
from scion_sdk.ingest.paging import CursorStrategy
from scion_sdk.ingest.service import KnowledgeIngest

from ._stream_writes import _StreamWrites

_LOG = logging.getLogger(__name__)
_MAX_CURSOR_HISTORY = 100_000

FetchPage = Callable[[str | None], Awaitable[Any]]


class _StreamPaging(_StreamWrites):
    """Commit mapped results and page through a source."""

    async def mapped(
        self,
        mapped: Mapped,
        *,
        cursor: str | None = None,
        ingest: KnowledgeIngest | None = None,
        _page_complete: bool = False,
    ) -> dict[str, int] | None:
        """Submit a :class:`Mapped` result; documents go to the document stream."""
        if not (mapped.entities or mapped.documents):
            self._refuse("mapping produced nothing to ingest")
            return None
        split = self.document_binding is not None and bool(mapped.documents)
        totals = {"nodes": 0, "edges": 0}
        if mapped.entities or not split:
            counts = await self._commit_entities(
                mapped,
                documents=() if split else tuple(mapped.documents),
                cursor=cursor,
                ingest=ingest,
                page_complete=_page_complete,
            )
            if counts is None:
                return None
            totals = _add(totals, counts)
        if split:
            counts = await self.submit(
                ChangeSet(documents=tuple(mapped.documents), cursor=cursor),
                binding=self.document_binding,
                ingest=ingest,
            )
            if counts is None:
                return None
            totals = _add(totals, counts)
        return totals

    async def _commit_entities(
        self,
        mapped: Mapped,
        *,
        documents: tuple[Any, ...],
        cursor: str | None,
        ingest: KnowledgeIngest | None,
        page_complete: bool,
    ) -> dict[str, int] | None:
        size = self.batch_size
        if size is None or not mapped.entities:
            return await self.submit(
                ChangeSet(
                    entities=tuple(mapped.entities),
                    documents=documents,
                    relationships=tuple(mapped.relationships),
                    cursor=cursor,
                    source_page=page_complete,
                ),
                ingest=ingest,
            )
        entities, edges = mapped.entities, mapped.relationships
        anchor = (entities[0],)
        totals = {"nodes": 0, "edges": 0}
        for start in range(0, len(entities), size):
            counts = await self.submit(
                ChangeSet(
                    entities=tuple(entities[start : start + size]),
                    preserve_cursor=True,
                    source_page=page_complete,
                ),
                ingest=ingest,
            )
            if counts is None:
                return None
            totals = _add(totals, counts)
        for start in range(0, len(edges), size):
            counts = await self.submit(
                ChangeSet(
                    entities=anchor,
                    relationships=tuple(edges[start : start + size]),
                    preserve_cursor=True,
                    source_page=page_complete,
                ),
                ingest=ingest,
            )
            if counts is None:
                return None
            totals = {
                "nodes": totals["nodes"],
                "edges": totals["edges"] + counts["edges"],
            }
        split = bool(mapped.documents) and not documents
        if documents or cursor or (page_complete and not split):
            counts = await self.submit(
                ChangeSet(
                    documents=documents,
                    cursor=cursor,
                    entities=anchor,
                    source_page=page_complete,
                ),
                ingest=ingest,
            )
            if counts is None:
                return None
        return totals

    async def records(
        self,
        kind: str,
        records: Sequence[Mapping[str, Any]],
        *,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int] | None:
        """Map ``records`` with the mapper declared for ``kind`` and ingest them."""
        try:
            mapped = self._mapper(kind, records)
        except IngestError as exc:
            if not self.best_effort:
                raise
            _LOG.debug("knowledge ingest skipped: %s", exc)
            return None
        return await self.mapped(mapped, ingest=ingest)

    def _mapper(self, kind: str, records: Sequence[Mapping[str, Any]]) -> Mapped:
        mapper = self.mappers.get(kind)
        if mapper is None:
            raise IngestError(f"unsupported record kind: {kind!r}")
        return apply_mapper(mapper, records)

    async def sync(
        self,
        kind: str,
        fetch_page: FetchPage,
        *,
        ingest: KnowledgeIngest | None = None,
        resume: bool = True,
        max_pages: int | None = None,
        strategy: CursorStrategy | None = None,
    ) -> dict[str, int]:
        """Page through a source and ingest each page, checkpointing the cursor.

        ``fetch_page(cursor)`` returns ``(records, next_cursor)``; ``None`` as
        the next cursor ends the walk. Each page commits with its next cursor,
        so a later run resumes from the stream's accepted cursor.

        With a ``strategy``, ``fetch_page(cursor)`` returns only the records and
        the strategy decides the next cursor (offset, key-set or time window).
        A page with documents on a separate binding is refused before submission:
        the two streams do not have an atomic checkpoint.
        """
        if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
            raise IngestError("max_pages must be a positive integer")
        service = ingest
        if service is None:
            from scion_sdk.ingest import current_ingest

            service = current_ingest()
        cursor = await service.accepted_cursor(self.binding) if resume else None
        if cursor is None and strategy is not None:
            cursor = strategy.first()
        totals = {"nodes": 0, "edges": 0}
        seen: set[bytes] = set()
        if cursor is not None:
            seen.add(_fingerprint(cursor))
        pages = 0
        while max_pages is None or pages < max_pages:
            fetched = await fetch_page(cursor)
            if strategy is None:
                records, next_cursor = fetched
            else:
                records = fetched
                next_cursor = strategy.advance(records, cursor)
            pages += 1
            _remember_cursor(seen, next_cursor)
            counts = await self._sync_page(kind, records, next_cursor, service)
            if counts is not None:
                totals = _add(totals, counts)
            if next_cursor is None:
                break
            cursor = next_cursor
        return totals

    async def _sync_page(
        self,
        kind: str,
        records: Sequence[Mapping[str, Any]],
        next_cursor: str | None,
        service: KnowledgeIngest,
    ) -> dict[str, int] | None:
        mapped = self._mapper(kind, records)
        if self.document_binding is not None and mapped.documents:
            raise IngestError("source sync cannot checkpoint split document streams")
        if mapped.entities or mapped.documents:
            counts = await self.mapped(
                mapped, cursor=next_cursor, ingest=service, _page_complete=True
            )
            if counts is None:
                raise IngestError("source page was not accepted")
            return counts
        if records:
            raise IngestError("source page mapping produced no records")
        if next_cursor is not None:
            # Empty windows still represent accepted source progress.  Do
            # not advance in memory until the checkpoint is durable.
            counts = await self.submit(
                ChangeSet(cursor=next_cursor, source_page=True), ingest=service
            )
            if counts is None:
                raise IngestError("source page was not accepted")
        return None


def _fingerprint(cursor: str) -> bytes:
    return hashlib.sha256(cursor.encode("utf-8")).digest()


def _remember_cursor(seen: set[bytes], next_cursor: object) -> None:
    if next_cursor is None:
        return
    if not isinstance(next_cursor, str):
        raise IngestError("source continuation must be a string")
    fingerprint = _fingerprint(next_cursor)
    if fingerprint in seen:
        raise IngestError("source continuation repeated")
    if len(seen) >= _MAX_CURSOR_HISTORY:
        raise IngestError("source continuation history limit exceeded")
    seen.add(fingerprint)


def _add(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {key: left[key] + right[key] for key in left}
