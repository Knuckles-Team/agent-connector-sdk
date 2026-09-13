"""SDK-side record, cursor, pack and receipt types (the epistemic-graph seam).

These types are the one place the SDK describes data it exchanges with
epistemic-graph. epistemic-graph owns the authoritative schema for content packs,
source records, cursors and receipts; once that contract is published, this
module is replaced by types generated from it, with explicit schema versions,
and every name here maps one-to-one onto a generated type. Until then the types
stay deliberately minimal: identity, payload, provenance and a canonical digest,
nothing an epistemic-graph import would have to reinterpret.

Every model is frozen. Digests are SHA-256 over canonical JSON (sorted keys, no
insignificant whitespace) prefixed with a versioned domain tag, so equal content
always yields an equal digest and a digest can never be confused with one of a
different type.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

__all__ = [
    "SEAM_SCHEMA_VERSION",
    "ArtifactEntry",
    "CapabilityDescriptor",
    "ContentPack",
    "IngestionReceipt",
    "PackImportReceipt",
    "PackRecord",
    "ReconciliationReport",
    "RecordBatch",
    "RecordPage",
    "RecordProvenance",
    "ServerIdentity",
    "SourceRecord",
    "StreamDescriptor",
    "SyncCursor",
    "canonical_digest",
]

#: Version of the SDK-side seam types. An epistemic-graph contract-generated
#: replacement carries its own version; mixing the two fails closed.
SEAM_SCHEMA_VERSION = "agent-connector-sdk.seam/1"


def canonical_digest(domain: str, value: Any) -> str:
    """Return ``sha256:<hex>`` over ``value``'s canonical JSON in ``domain``."""
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    digest = hashlib.sha256(domain.encode("utf-8") + b"\x00" + payload).hexdigest()
    return f"sha256:{digest}"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CapabilityDescriptor(_Frozen):
    """What one extension declares about itself before it is activated."""

    kind: str
    schema_version: str = SEAM_SCHEMA_VERSION
    pagination: tuple[str, ...] = ()
    incremental: bool = False
    certified_for_ingestion: bool = False
    credential_references: tuple[str, ...] = ()


class StreamDescriptor(_Frozen):
    """A source stream whose live contract was verified by ``discover``."""

    stream: str
    tool: str
    schema_sha256: str


class RecordProvenance(_Frozen):
    """Where one record came from. Every field is required and non-empty."""

    connector: str = Field(min_length=1)
    adapter_kind: str = Field(min_length=1)
    server: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    tool_schema_sha256: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)


class SourceRecord(_Frozen):
    """One raw record extracted from a source, before any mapping is applied."""

    stream: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    payload: dict[str, JsonValue]
    updated_at: str | None = None
    provenance: RecordProvenance

    @property
    def content_digest(self) -> str:
        """Digest of the identity and payload, independent of retrieval time."""
        return canonical_digest(
            "agent-connector-sdk:source-record:v1",
            {
                "stream": self.stream,
                "record_id": self.record_id,
                "payload": self.payload,
                "updated_at": self.updated_at,
            },
        )


class SyncCursor(_Frozen):
    """Resumable position of one stream.

    ``position`` is adapter-private pagination state. ``watermark`` is the high
    water mark of the last completed sweep; ``pending_watermark`` accumulates
    the high water mark of a sweep that has not finished yet, so a resumed
    sweep keeps filtering against the last *completed* watermark.
    """

    stream: str = Field(min_length=1)
    position: dict[str, JsonValue] = Field(default_factory=dict)
    watermark: str | None = None
    pending_watermark: str | None = None


class RecordPage(_Frozen):
    """One extracted page and the cursor that resumes after it."""

    records: tuple[SourceRecord, ...]
    cursor: SyncCursor
    exhausted: bool


class RecordBatch(_Frozen):
    """Records submitted to a sink with the mapping they must be applied with."""

    connector: str = Field(min_length=1)
    mapping_reference: str = Field(min_length=1)
    records: tuple[SourceRecord, ...]
    cursor: SyncCursor

    @property
    def digest(self) -> str:
        """Digest over the mapping reference, record digests and cursor."""
        return canonical_digest(
            "agent-connector-sdk:record-batch:v1",
            {
                "connector": self.connector,
                "mapping_reference": self.mapping_reference,
                "records": [record.content_digest for record in self.records],
                "cursor": self.cursor.model_dump(mode="json"),
            },
        )


class IngestionReceipt(_Frozen):
    """A sink's acknowledgement that a batch was durably committed."""

    batch_digest: str
    accepted: int = Field(ge=0)
    committed_cursor: SyncCursor


class ReconciliationReport(_Frozen):
    """Differences between the ids a sink knows and the ids the source serves."""

    stream: str
    missing_from_source: tuple[str, ...]
    unknown_to_sink: tuple[str, ...]


class ServerIdentity(_Frozen):
    """The MCP server a content pack was read from."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ArtifactEntry(_Frozen):
    """One unit of MCP-served content (a tool, skill, prompt or resource)."""

    kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    body: str
    server: ServerIdentity

    @property
    def digest(self) -> str:
        """Digest over kind, URI, media type and body."""
        return canonical_digest(
            "agent-connector-sdk:artifact-entry:v1",
            {
                "kind": self.kind,
                "uri": self.uri,
                "media_type": self.media_type,
                "body": self.body,
            },
        )


class PackRecord(_Frozen):
    """The record one artifact entry maps to on import."""

    record_kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    name: str = Field(min_length=1)
    entry_digest: str = Field(min_length=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class ContentPack(_Frozen):
    """A connector's MCP-served content snapshot."""

    connector: str = Field(min_length=1)
    server: ServerIdentity
    entries: tuple[ArtifactEntry, ...]

    @property
    def digest(self) -> str:
        """Digest over the server identity and the sorted entry digests."""
        return canonical_digest(
            "agent-connector-sdk:content-pack:v1",
            {
                "connector": self.connector,
                "server": self.server.model_dump(mode="json"),
                "entries": sorted(entry.digest for entry in self.entries),
            },
        )


class PackImportReceipt(_Frozen):
    """A sink's acknowledgement that a content pack was imported."""

    pack_digest: str
    imported: int = Field(ge=0)
