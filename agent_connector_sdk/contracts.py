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

from agent_connector_sdk.schema_drift import EvolutionPolicy, SchemaContract

__all__ = [
    "CONNECTOR_UNCONFIGURED_MARKING",
    "SEAM_SCHEMA_VERSION",
    "CapabilityDescriptor",
    "CapturedArtifact",
    "ExternalAccess",
    "ReconciliationReport",
    "RecordPage",
    "ServerIdentity",
    "StreamDescriptor",
    "default_external_access",
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
    schema_contract: SchemaContract | None = None
    evolution_policy: EvolutionPolicy = EvolutionPolicy.REVIEW


class RecordPage(_Frozen):
    """One provider page mapped into EG's generated ingestion values."""

    records: tuple[SourceRecord, ...]
    mode: SourceIngestionMode
    strict_schema: bool
    checkpoint: SourceCheckpoint
    exhausted: bool
    schema_contract: SchemaContract | None = None
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


#: Marking on a record whose source reported no ACL. No principal holds it by
#: default, so the record is readable by nobody until an operator grants it.
CONNECTOR_UNCONFIGURED_MARKING = "connector-unconfigured-acl"


class ExternalAccess(BaseModel):
    """The access-control facts a source reports for one record (SDK-CONNECTOR-CONTROL-R014.13).

    A per-record ACL a connector stamps onto an ingested payload: either
    world-public, or readable by explicit users, groups or provider-neutral
    read roles, optionally under mandatory compartment markings. Replaces
    ``agent_utilities.protocols.source_connectors.base.ExternalAccess``.
    """

    model_config = ConfigDict(extra="forbid")

    is_public: bool = False
    user_emails: list[str] = Field(default_factory=list)
    group_ids: list[str] = Field(default_factory=list)
    read_roles: list[str] = Field(default_factory=list)
    markings: list[str] = Field(default_factory=list)

    @classmethod
    def public(cls) -> ExternalAccess:
        """A world-readable descriptor."""
        return cls(is_public=True)

    @classmethod
    def quarantined(cls) -> ExternalAccess:
        """The fail-closed descriptor: no principals, the unconfigured marking."""
        return cls(is_public=False, markings=[CONNECTOR_UNCONFIGURED_MARKING])


def default_external_access() -> ExternalAccess:
    """The descriptor for a source that reports no ACL: never public."""
    return ExternalAccess.quarantined()
