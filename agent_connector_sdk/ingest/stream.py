"""The one ingest entry a connector declares: a binding plus its mappers.

:class:`SourceStream` replaces the per-connector ``kg_ingest.py`` plumbing. It
builds change sets from mapped records, submits them to the process's
:class:`~agent_connector_sdk.ingest.service.KnowledgeIngest`, pages through a
source resuming from the stream's durable cursor, and returns the standard
``{"nodes": n, "edges": n}`` counts.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from agent_connector_sdk.ingest.errors import IngestError
from agent_connector_sdk.ingest.mapping import (
    Mapped,
    Mapper,
    apply_mapper,
    document_from_record,
    entity_from_record,
    relationship_from_record,
)
from agent_connector_sdk.ingest.model import ChangeSet, IngestBinding, MediaAsset
from agent_connector_sdk.ingest.service import KnowledgeIngest

_LOG = logging.getLogger(__name__)

__all__ = ["FetchPage", "SourceStream", "open_client"]

FetchPage = Callable[
    [str | None], Awaitable[tuple[Sequence[Mapping[str, Any]], str | None]]
]


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
    ) -> None:
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
        try:
            if ingest is None:
                from agent_connector_sdk.ingest import current_ingest

                ingest = current_ingest()
            receipt = await ingest.submit(binding or self.binding, change_set)
        except IngestError as exc:
            if not self.best_effort:
                raise
            _LOG.debug("knowledge ingest skipped: %s", exc)
            return None
        return {"nodes": receipt.affected_count, "edges": receipt.relationship_count}

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
        try:
            change_set = ChangeSet(
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
        use = self.document_binding if not entities else None
        return await self.submit(change_set, binding=use, ingest=ingest)

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
    ) -> dict[str, int] | None:
        """Submit a :class:`Mapped` result; documents go to the document stream."""
        if not (mapped.entities or mapped.documents):
            self._refuse("mapping produced nothing to ingest")
            return None
        split = self.document_binding is not None and mapped.documents
        totals = {"nodes": 0, "edges": 0}
        if mapped.entities or not split:
            counts = await self.submit(
                ChangeSet(
                    entities=tuple(mapped.entities),
                    documents=() if split else tuple(mapped.documents),
                    relationships=tuple(mapped.relationships),
                    cursor=cursor,
                ),
                ingest=ingest,
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
    ) -> dict[str, int]:
        """Page through a source and ingest each page, checkpointing the cursor.

        ``fetch_page(cursor)`` returns ``(records, next_cursor)``; ``None`` as
        the next cursor ends the walk. Each page commits with its next cursor,
        so a later run resumes from the stream's accepted cursor.
        """
        service = ingest
        if service is None:
            from agent_connector_sdk.ingest import current_ingest

            service = current_ingest()
        cursor = await service.accepted_cursor(self.binding) if resume else None
        totals = {"nodes": 0, "edges": 0}
        pages = 0
        while max_pages is None or pages < max_pages:
            records, next_cursor = await fetch_page(cursor)
            pages += 1
            mapped = self._mapper(kind, records)
            if mapped.entities or mapped.documents:
                counts = await self.mapped(mapped, cursor=next_cursor, ingest=service)
                if counts is not None:
                    totals = _add(totals, counts)
            if next_cursor is None or next_cursor == cursor:
                break
            cursor = next_cursor
        return totals


def _add(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {key: left[key] + right[key] for key in left}
