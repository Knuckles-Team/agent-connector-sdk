"""Binding, projection and the single submit path of a source stream."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Self

from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.mapping import Mapper
from scion_sdk.ingest.model import ChangeSet, IngestBinding
from scion_sdk.ingest.service import KnowledgeIngest

_LOG = logging.getLogger(__name__)


class _StreamBase:
    """State and submit path shared by every :class:`SourceStream` capability."""

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
    ) -> Self:
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
            return await self._commit(change_set, binding, ingest)
        except IngestError as exc:
            if not self.best_effort:
                raise
            _LOG.debug("knowledge ingest skipped: %s", exc)
            return None

    async def _commit(
        self,
        change_set: ChangeSet,
        binding: IngestBinding | None,
        ingest: KnowledgeIngest | None,
    ) -> Any:
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

    def _check_size(self, change_set: ChangeSet) -> None:
        count = len(change_set.entities) + len(change_set.documents)
        if self.max_records is not None and count > self.max_records:
            raise IngestError(f"at most {self.max_records} records per change set")

    def scoped(self, suffix: str, **binding_fields: Any) -> Self:
        """A copy whose stream is ``<stream>:<suffix>``, with binding overrides.

        Use it for a per-account or per-instance checkpoint.
        """
        binding = replace(
            self.binding, stream=f"{self.binding.stream}:{suffix}", **binding_fields
        )
        copy = type(self)(
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
