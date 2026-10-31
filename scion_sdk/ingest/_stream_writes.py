"""Record writers of a source stream: entities, documents and media."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.mapping import (
    document_from_record,
    entity_from_record,
    relationship_from_record,
)
from scion_sdk.ingest.model import ChangeSet, MediaAsset
from scion_sdk.ingest.service import KnowledgeIngest

from ._stream_base import _StreamBase

_LOG = logging.getLogger(__name__)


class _StreamWrites(_StreamBase):
    """Write entities, documents and media through the submit path."""

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
