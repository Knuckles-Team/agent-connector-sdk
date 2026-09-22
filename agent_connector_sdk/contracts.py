"""SDK-owned connector authoring and extraction types.

The durable source-ingestion contract is imported directly from
``epistemic_graph.generated.source_ingestion`` by its consumers. This module
contains only SDK-side descriptions and MCP content captured before it is mapped
into an epistemic-graph request.

Every model is frozen. Canonical graph-boundary identity and digests remain in
the generated epistemic-graph contract rather than being recomputed here.
"""

from __future__ import annotations

from epistemic_graph.generated.connector_pack import PackAnnotations
from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceEntityRef,
    SourceIngestionMode,
    SourceRecord,
    SourceRelationship,
    SourceWithdrawal,
)
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SEAM_SCHEMA_VERSION",
    "CapabilityDescriptor",
    "CapturedArtifact",
    "ReconciliationReport",
    "RecordPage",
    "ServerIdentity",
    "StreamDescriptor",
]

#: Version of the SDK-side seam types. An epistemic-graph contract-generated
#: replacement carries its own version; mixing the two fails closed.
SEAM_SCHEMA_VERSION = "agent-connector-sdk.seam/1"


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


class RecordPage(_Frozen):
    """One provider page mapped into EG's generated ingestion values."""

    records: tuple[SourceRecord, ...]
    mode: SourceIngestionMode
    strict_schema: bool
    checkpoint: SourceCheckpoint
    exhausted: bool
    relationships: tuple[SourceRelationship, ...] = ()
    authoritative_live_ids: tuple[SourceEntityRef, ...] | None = None
    withdrawals: tuple[SourceWithdrawal, ...] = ()


class ReconciliationReport(_Frozen):
    """Differences between the ids a sink knows and the ids the source serves."""

    stream: str
    missing_from_source: tuple[str, ...]
    unknown_to_sink: tuple[str, ...]


class ServerIdentity(_Frozen):
    """The MCP server a content pack was read from."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class CapturedArtifact(_Frozen):
    """MCP-served content captured before generated pack construction."""

    kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    body: str
    server: ServerIdentity
    annotations: PackAnnotations = Field(default_factory=PackAnnotations)
