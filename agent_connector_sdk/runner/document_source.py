"""Manifest-bound pages from a polled document connector.

The provider supplies one page and its *actual* resumable cursor at a time.
Epistemic Graph owns the accepted cursor; the SDK never synthesizes a sequence
for this source shape. A connector must publish its manifest before the first
page can be admitted by SourceIngest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
    SourceRecord,
    SourceRecordProvenance,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from agent_connector_sdk.contracts import RecordPage
from agent_connector_sdk.manifest.model import ConnectorManifest
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.privacy import PersistencePrivacyGuard
from agent_connector_sdk.runner.errors import SinkReceiptError
from agent_connector_sdk.runner.syncing import SyncOutcome

__all__ = [
    "DocumentObservation",
    "DocumentPollAdapter",
    "DocumentProviderPage",
    "sync_document_source",
]

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_QUARANTINE = "connector-unconfigured-acl"
_DOCUMENT_FIELDS = ("text", "title", "doc_type", "metadata", "external_access")


@dataclass(frozen=True)
class DocumentObservation:
    """A provider document; unknown access gets a quarantine marking."""

    id: str
    text: str
    title: str = ""
    doc_type: str = "document"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    external_access: Mapping[str, Any] | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class DocumentProviderPage:
    """One provider page with its exact JSON cursor after these records."""

    documents: tuple[DocumentObservation, ...]
    position: JsonValue
    exhausted: bool
    watermark: str | None = None
    content_hash: str | None = None


DocumentPoll = Callable[[SourceCheckpoint | None], Awaitable[DocumentProviderPage]]


class DocumentSink(Protocol):
    """The generated SourceIngest operations; an EG client provides these."""

    async def source_status(
        self, connector: str, stream: str
    ) -> SourceIngestStatus: ...

    async def submit(
        self, request: SourceIngestionRequest
    ) -> SourceIngestionReceipt: ...


class DocumentPollAdapter:
    """Convert declared document pages to generated EG SourceIngest values.

    ``poll`` receives only EG's accepted checkpoint, including the provider's
    original ``position``. It must return one page; the caller commits that
    page before asking for another. No legacy cursor store is consulted.
    """

    def __init__(
        self,
        manifest: ConnectorManifest,
        *,
        stream: str,
        mapping_key: str,
        poll: DocumentPoll,
        provider_contract_sha256: str,
        server: str,
        tool: str,
    ) -> None:
        mapping = manifest.schema_mappings.get(mapping_key)
        if mapping is None or mapping.ontology_class != "Document":
            raise SourceContractError("provider has no declared Document mapping")
        if "external_access" not in manifest.permissions.acl_fields:
            raise SourceContractError("Document mapping has no declared ACL field")
        if any(mapping.fields.get(name) != name for name in _DOCUMENT_FIELDS):
            raise SourceContractError(
                "Document mapping drops a required document field"
            )
        if not all((stream, server, tool)):
            raise SourceContractError("stream and provider provenance are required")
        if len(provider_contract_sha256) != 64 or any(
            digit not in "0123456789abcdef" for digit in provider_contract_sha256
        ):
            raise SourceContractError("provider contract needs a SHA-256 pin")
        self.manifest = manifest
        self.stream = stream
        self.mapping_reference = (
            f"manifest:{manifest.connector}#schema_mappings/{mapping_key}"
        )
        self.poll = poll
        self.provider_contract_sha256 = provider_contract_sha256
        self.server = server
        self.tool = tool

    async def extract(self, checkpoint: SourceCheckpoint | None) -> RecordPage:
        """Read one page after a durable checkpoint and map all records."""
        if checkpoint is not None and checkpoint.stream != self.stream:
            raise SourceContractError("checkpoint belongs to another stream")
        page = await self.poll(checkpoint)
        if not page.exhausted and page.position == (
            checkpoint.position if checkpoint is not None else None
        ):
            raise SourceContractError("provider page did not advance its cursor")
        if page.content_hash is not None and (
            len(page.content_hash) != 64
            or any(digit not in "0123456789abcdef" for digit in page.content_hash)
        ):
            raise SourceContractError("provider content hash is not SHA-256")
        records = tuple(self._record(document) for document in page.documents)
        if len({record.record_id for record in records}) != len(records):
            raise MalformedSourceDataError("provider page repeats a document id")
        try:
            position = _JSON_OBJECT.validate_python(page.position)
            next_checkpoint = SourceCheckpoint(
                stream=self.stream,
                position=position,
                content_hash=page.content_hash,
                watermark=(
                    page.watermark
                    or (
                        checkpoint.pending_watermark if checkpoint is not None else None
                    )
                )
                if page.exhausted
                else (checkpoint.watermark if checkpoint is not None else None),
                pending_watermark=(
                    None
                    if page.exhausted
                    else (
                        page.watermark
                        or (
                            checkpoint.pending_watermark
                            if checkpoint is not None
                            else None
                        )
                    )
                ),
            )
        except ValidationError as exc:
            raise MalformedSourceDataError(
                "provider checkpoint is not JSON data"
            ) from exc
        return RecordPage(
            records=records,
            mode=SourceIngestionMode.DELTA,
            strict_schema=True,
            checkpoint=next_checkpoint,
            exhausted=page.exhausted,
        )

    def _record(self, document: DocumentObservation) -> SourceRecord:
        if not document.id.strip() or not document.text.strip():
            raise MalformedSourceDataError("document needs an id and nonempty text")
        access = document.external_access or {
            "is_public": False,
            "markings": [_QUARANTINE],
        }
        if not isinstance(access.get("is_public"), bool):
            raise MalformedSourceDataError(
                "document access lacks an explicit public flag"
            )
        if not access["is_public"] and not any(
            access.get(name)
            for name in ("user_emails", "group_ids", "read_roles", "markings")
        ):
            access = {**access, "markings": [_QUARANTINE]}
        guard = PersistencePrivacyGuard()
        metadata, _ = guard.sanitize(dict(document.metadata))
        try:
            payload = _JSON_OBJECT.validate_python(
                {
                    "id": document.id,
                    "text": document.text,
                    "title": document.title,
                    "doc_type": document.doc_type,
                    "metadata": metadata,
                    "external_access": dict(access),
                }
            )
        except ValidationError as exc:
            raise MalformedSourceDataError("document payload is not JSON data") from exc
        opaque_id = hashlib.sha256(document.id.encode("utf-8")).hexdigest()
        return SourceRecord(
            stream=self.stream,
            record_id=document.id,
            mapping_reference=self.mapping_reference,
            payload=payload,
            updated_at=document.updated_at,
            provenance=SourceRecordProvenance(
                connector=self.manifest.connector,
                adapter_kind="document_poll",
                server=self.server,
                tool=self.tool,
                tool_schema_sha256=self.provider_contract_sha256,
                source_uri=f"connector://{self.manifest.connector}/{opaque_id}",
            ),
        )


async def sync_document_source(
    adapter: DocumentPollAdapter,
    sink: DocumentSink,
    *,
    max_pages: int,
) -> SyncOutcome:
    """Poll and commit each page before reading the next provider cursor.

    ``sink`` can be :class:`EpistemicGraphIngestTransport` built around the
    caller's already verified EG client. A checkpoint conflict is surfaced to
    the caller; retrying the same drained page against a new cursor is unsafe.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    connector = adapter.manifest.connector
    status = await sink.source_status(connector, adapter.stream)
    if status.connector != connector or status.stream != adapter.stream:
        raise SinkReceiptError("source status does not bind the requested stream")
    checkpoint = status.accepted_checkpoint
    pages = records = accepted = 0
    exhausted = False
    while pages < max_pages and not exhausted:
        page = await adapter.extract(checkpoint)
        if page.checkpoint == checkpoint and not page.records and page.exhausted:
            exhausted = True
            break
        request = SourceIngestionRequest(
            connector=connector,
            mode=page.mode,
            strict_schema=page.strict_schema,
            records=list(page.records),
            relationships=[],
            provider_checkpoint=page.checkpoint,
            expected_previous_checkpoint=checkpoint,
        )
        receipt = await sink.submit(request)
        if (
            receipt.batch_digest != request.canonical_digest()
            or receipt.accepted_checkpoint != page.checkpoint
            or receipt.mode != page.mode
        ):
            raise SinkReceiptError("ingestion receipt does not bind the provider page")
        checkpoint = receipt.accepted_checkpoint
        pages += 1
        records += len(page.records)
        accepted += receipt.affected_count
        exhausted = page.exhausted
    return SyncOutcome(adapter.stream, pages, records, accepted, exhausted, checkpoint)
