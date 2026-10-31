"""Governed-change rendering and batch result types for the GraphQL document connector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scion_sdk.adapters.document_sources import access_properties
from scion_sdk.data_prep._classification import DataClassification
from scion_sdk.ingest.model import Entity, Withdrawal

from ..base import (
    ConnectorCheckpoint,
    ExternalAccess,
    SourceDocument,
)

#: One governed change: an upsert entity or a withdrawal.
GovernedChange = Entity | Withdrawal


def _governed_change(
    *,
    source_object_id: str,
    source_version: str,
    operation: str = "upsert",
    typed_payload: dict[str, Any] | None = None,
    source_acl: ExternalAccess | None = None,
    classification: DataClassification = DataClassification.INTERNAL,
    retention: str | None = None,
    legal_hold: bool = False,
    tenant: str = "",
    schema_version: str = "",
    ontology_mapping_version: str = "",
    provenance: dict[str, Any] | None = None,
    source_instance: str = "",
    **_: Any,
) -> GovernedChange:
    """Render one governed change as an SDK entity or withdrawal."""
    if operation == "delete":
        return Withdrawal(id=source_object_id, reason=f"absent at {source_version}")
    payload = dict(typed_payload or {})
    governance = {
        "source_instance": source_instance,
        "source_version": source_version,
        "tenant": tenant,
        "schema_version": schema_version,
        "ontology_mapping_version": ontology_mapping_version,
        "classification": DataClassification(classification).value,
        "retention": retention,
        "legal_hold": legal_hold,
        "provenance": dict(provenance or {}),
    }
    if source_acl is not None:
        governance.update(access_properties(source_acl))
    return Entity(
        id=source_object_id,
        node_type=str(payload.get("type") or "Entity"),
        properties={**payload, **governance},
    )


@dataclass(frozen=True)
class GraphQLHierarchyBatch:
    """One bounded GraphQL read mapped to embedding documents and envelopes."""

    documents: tuple[SourceDocument, ...] = ()
    envelopes: tuple[GovernedChange, ...] = ()
    checkpoint: ConnectorCheckpoint = field(default_factory=ConnectorCheckpoint)
    diagnostics: dict[str, Any] = field(default_factory=dict)
