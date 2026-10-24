"""The one ingest entry a connector declares: a binding plus its mappers.

:class:`SourceStream` replaces the per-connector ``kg_ingest.py`` plumbing. It
builds change sets from mapped records, submits them to the process's
:class:`~agent_connector_sdk.ingest.service.KnowledgeIngest`, pages through a
source resuming from the stream's durable cursor, and returns the standard
``{"nodes": n, "edges": n}`` counts.
"""

from __future__ import annotations

import inspect
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
from agent_connector_sdk.ingest.model import ChangeSet, IngestBinding
from agent_connector_sdk.ingest.service import KnowledgeIngest

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
    """A connector's ingest stream: binding, named mappers, and the submit path."""

    def __init__(
        self,
        binding: IngestBinding,
        mappers: Mapping[str, Mapper | Sequence[Mapper]] | None = None,
    ) -> None:
        self.binding = binding
        self.mappers = dict(mappers or {})

    @classmethod
    def for_package(
        cls,
        package: str,
        stream: str,
        mappers: Mapping[str, Mapper | Sequence[Mapper]] | None = None,
        **binding_fields: Any,
    ) -> SourceStream:
        """A stream bound under ``package``'s declared fleet name."""
        return cls(
            IngestBinding.for_package(package, stream, **binding_fields), mappers
        )

    async def _submit(
        self, change_set: ChangeSet, ingest: KnowledgeIngest | None
    ) -> dict[str, int]:
        if ingest is None:
            from agent_connector_sdk.ingest import current_ingest

            ingest = current_ingest()
        receipt = await ingest.submit(self.binding, change_set)
        return {"nodes": receipt.affected_count, "edges": receipt.relationship_count}

    async def entities(
        self,
        entities: Sequence[Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]] | None = None,
        *,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int]:
        """Write ``{"id", "node_type", ...}`` records and edges as typed nodes."""
        if not entities:
            raise IngestError("ingest needs at least one entity")
        return await self._submit(
            ChangeSet(
                entities=tuple(entity_from_record(e) for e in entities),
                relationships=tuple(
                    relationship_from_record(r) for r in relationships or ()
                ),
            ),
            ingest,
        )

    async def documents(
        self,
        documents: Sequence[Mapping[str, Any]],
        *,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int]:
        """Write ``{"id", "text", "title"?, "source_uri"?}`` records as documents."""
        if not documents:
            raise IngestError("ingest needs at least one document")
        return await self._submit(
            ChangeSet(documents=tuple(document_from_record(d) for d in documents)),
            ingest,
        )

    async def mapped(
        self,
        mapped: Mapped,
        *,
        cursor: str | None = None,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int]:
        """Submit a :class:`Mapped` result as one change set."""
        if not (mapped.entities or mapped.documents):
            raise IngestError("mapping produced nothing to ingest")
        return await self._submit(
            ChangeSet(
                entities=tuple(mapped.entities),
                documents=tuple(mapped.documents),
                relationships=tuple(mapped.relationships),
                cursor=cursor,
            ),
            ingest,
        )

    async def records(
        self,
        kind: str,
        records: Sequence[Mapping[str, Any]],
        *,
        ingest: KnowledgeIngest | None = None,
    ) -> dict[str, int]:
        """Map ``records`` with the mapper declared for ``kind`` and ingest them."""
        return await self.mapped(self._mapper(kind, records), ingest=ingest)

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
                totals["nodes"] += counts["nodes"]
                totals["edges"] += counts["edges"]
            if next_cursor is None or next_cursor == cursor:
                break
            cursor = next_cursor
        return totals
