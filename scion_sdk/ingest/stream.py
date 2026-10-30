"""The one ingest entry a connector declares: a binding plus its mappers.

:class:`SourceStream` replaces the per-connector ``kg_ingest.py`` plumbing. It
builds change sets from mapped records, submits them to the process's
:class:`~scion_sdk.ingest.service.KnowledgeIngest`, pages through a
source resuming from the stream's durable cursor, and returns the standard
``{"nodes": n, "edges": n}`` counts.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.mapping import (
    Mapped,
    Mapper,
    apply_mapper,
    document_from_record,
    entity_from_record,
    relationship_from_record,
)
from scion_sdk.ingest.model import ChangeSet, IngestBinding, MediaAsset
from scion_sdk.ingest.paging import CursorStrategy
from scion_sdk.ingest.service import KnowledgeIngest

_LOG = logging.getLogger(__name__)
_MAX_CURSOR_HISTORY = 100_000

__all__ = ["FetchPage", "SourceStream", "open_client"]

FetchPage = Callable[[str | None], Awaitable[Any]]


@asynccontextmanager
async def open_client(get_client: Callable[..., Any]) -> AsyncIterator[Any]:
    """Build a connector client from its ``get_client`` factory and close it after.

    The factory may be sync or async; ``aclose`` or ``close`` is called when
    the client has one.
    """
    client = get_client()
    if inspect.isawaitable(client):
        client = await client
    try:
        yield client
    finally:
        for name in ("aclose", "close"):
            closer = getattr(client, name, None)
            if callable(closer):
                result = closer()
                if inspect.isawaitable(result):
                    await result
                break


class SourceStream:
    """A connector's ingest stream: binding, named mappers, and the submit path.

    Args:
        binding: Where entity change sets land.
        mappers: Record-kind name to :data:`Mapper` (or a sequence of them).
        document_binding: A second binding for documents, when documents live
            in their own stream.
        projection: Applied to every change set inside :meth:`submit`, before the
            commit (for example :meth:`Pseudonymizer.project
            <scion_sdk.ingest.privacy.Pseudonymizer.project>`).
        before_submit: A guard called with the binding and the projected change
            set; it raises :class:`IngestError` to stop the commit.
        max_records: Refuse a change set with more entities and documents.
        batch_size: Commit a :class:`Mapped` result in batches of this many
            records: all entities first, then the relationships.
        best_effort: Never raise. Empty input, records without an id (or a
            document without text), a refused commit and an unavailable engine
            return ``None`` and log at debug level.
    """

    def __init__(
        self,
        binding: IngestBinding,
        mappers: Mapping[str, Mapper | Sequence[Mapper]] | None = None,
        *,
        document_binding: IngestBinding | None = None,
        best_effort: bool = False,
        projection: Callable[[ChangeSet], ChangeSet] | None = None,
        before_submit: Callable[[IngestBinding, ChangeSet], None] | None = None,
        max_records: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        for name, value in (("max_records", max_records), ("batch_size", batch_size)):
            if value is not None and (type(value) is not int or value < 1):
                raise IngestError(f"{name} must be a positive integer")
        self.projection = projection
        self.before_submit = before_submit
        self.max_records = max_records
        self.batch_size = batch_size
        self.binding = binding
        self.mappers = dict(mappers or {})
        self.document_binding = document_binding
        self.best_effort = best_effort

    @classmethod
    def for_package(
        cls,
        package: str,
        stream: str,
        mappers: Mapping[str, Mapper | Sequence[Mapper]] | None = None,
        *,
        documents_stream: str | None = None,
        best_effort: bool = False,
        **binding_fields: Any,
    ) -> SourceStream:
        """A stream bound under ``package``'s declared fleet name.

        ``documents_stream`` names a second stream for documents.
        """
        binding = IngestBinding.for_package(package, stream, **binding_fields)
        documents = (
            IngestBinding.for_package(package, documents_stream, **binding_fields)
            if documents_stream
            else None
        )
        return cls(
            binding, mappers, document_binding=documents, best_effort=best_effort
        )

    async def submit(
        self,
        change_set: ChangeSet,
        *,
        binding: IngestBinding | None = None,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int] | None:
        """Commit ``change_set`` under ``binding`` (default: the stream's).

        The one submit path every other method uses; call it directly for a
        change set the other methods do not build (a reconcile, a mixed set).
        """
        receipt = await self.submit_receipt(change_set, binding=binding, ingest=ingest)
        if receipt is None:
            return None
        return {"nodes": receipt.affected_count, "edges": receipt.relationship_count}

    async def submit_receipt(
        self,
        change_set: ChangeSet,
        *,
        binding: IngestBinding | None = None,
        ingest: KnowledgeIngest | None = None,
    ) -> Any:
        """:meth:`submit`, returning the engine's receipt (``None`` when skipped)."""
        try:
            self._check_size(change_set)
            if self.projection is not None:
                change_set = self.projection(change_set)
            target = binding or self.binding
            if self.before_submit is not None:
                self.before_submit(target, change_set)
            if ingest is None:
                from scion_sdk.ingest import current_ingest

                ingest = current_ingest()
            return await ingest.submit(target, change_set)
        except IngestError as exc:
            if not self.best_effort:
                raise
            _LOG.debug("knowledge ingest skipped: %s", exc)
            return None

    def _check_size(self, change_set: ChangeSet) -> None:
        count = len(change_set.entities) + len(change_set.documents)
        if self.max_records is not None and count > self.max_records:
            raise IngestError(f"at most {self.max_records} records per change set")

    def scoped(self, suffix: str, **binding_fields: Any) -> SourceStream:
        """A copy whose stream is ``<stream>:<suffix>``, with binding overrides.

        Use it for a per-account or per-instance checkpoint.
        """
        binding = replace(
            self.binding, stream=f"{self.binding.stream}:{suffix}", **binding_fields
        )
        copy = SourceStream(
            binding,
            self.mappers,
            document_binding=self.document_binding,
            best_effort=self.best_effort,
            projection=self.projection,
            before_submit=self.before_submit,
            max_records=self.max_records,
            batch_size=self.batch_size,
        )
        return copy

    def _refuse(self, message: str) -> None:
        if not self.best_effort:
            raise IngestError(message)

    async def entities(
        self,
        entities: Sequence[Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]] | None = None,
        *,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int] | None:
        """Write ``{"id", "node_type", ...}`` records and edges as typed nodes."""
        return await self.batch(entities, relationships, ingest=ingest)

    async def documents(
        self,
        documents: Sequence[Mapping[str, Any]],
        *,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int] | None:
        """Write ``{"id", "text", "title"?, "source_uri"?}`` records as documents."""
        return await self.batch((), (), documents, ingest=ingest)

    async def batch(
        self,
        entities: Sequence[Mapping[str, Any]] = (),
        relationships: Sequence[Mapping[str, Any]] | None = None,
        documents: Sequence[Mapping[str, Any]] = (),
        *,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int] | None:
        """Write entities, edges and documents as one change set.

        With a ``document_binding`` and no entities, the set lands in the
        document stream.
        """
        if self.best_effort:
            entities = [e for e in entities or () if e.get("id")]
            documents = [d for d in documents or () if d.get("id") and d.get("text")]
        if not entities and not documents:
            self._refuse("ingest needs at least one entity or document")
            return None
        change_set = self._change_set(entities, relationships, documents)
        if change_set is None:
            return None
        use = self.document_binding if not entities else None
        return await self.submit(change_set, binding=use, ingest=ingest)

    def _change_set(
        self,
        entities: Sequence[Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]] | None,
        documents: Sequence[Mapping[str, Any]],
    ) -> ChangeSet | None:
        try:
            return ChangeSet(
                entities=tuple(entity_from_record(e) for e in entities),
                relationships=tuple(
                    relationship_from_record(r) for r in relationships or ()
                ),
                documents=tuple(document_from_record(d) for d in documents),
            )
        except IngestError as exc:
            if not self.best_effort:
                raise
            _LOG.debug("knowledge ingest skipped: %s", exc)
            return None

    async def media(
        self,
        data: bytes,
        mime_type: str,
        *,
        id: str | None = None,
        name: str = "",
        properties: Mapping[str, Any] | None = None,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int] | None:
        """Store binary content and its asset record."""
        if not data:
            self._refuse("ingest requires non-empty bytes")
            return None
        asset = MediaAsset(data, mime_type, id, name, dict(properties or {}))
        return await self.submit(ChangeSet(media=(asset,)), ingest=ingest)

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
