"""Pure checkpoint-state helpers for the GraphQL document connector."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scion_sdk.data_prep._classification import DataClassification

from ..base import (
    ExternalAccess,
    SourceDocument,
)
from ._graphql_base import (
    _RETENTION_RE,
    GraphQLDocumentError,
)
from ._graphql_change import GovernedChange
from ._graphql_settings import (
    _access_from_config,
)
from ._graphql_values import (
    _classification,
    _safe_alias,
)


def _validate_checkpoint_sequence(prior_state: dict[str, Any]) -> int:
    try:
        prior_sequence = int(prior_state.get("snapshot_sequence") or 0)
    except (TypeError, ValueError):
        raise GraphQLDocumentError("GraphQL checkpoint state is invalid") from None
    if prior_sequence < 0:
        raise GraphQLDocumentError("GraphQL checkpoint state is invalid")
    return prior_sequence


def _validate_snapshot_completeness(
    diagnostics: dict[str, Any],
    snapshot_authoritative: bool,
    baseline: dict[str, str],
    versions: dict[str, str],
    allow_empty_snapshot: bool,
) -> None:
    incomplete_reasons = sum(
        int(diagnostics.get(key) or 0)
        for key in ("truncated", "partial_errors", "invalid_records")
    )
    if snapshot_authoritative and incomplete_reasons:
        raise GraphQLDocumentError(
            "GraphQL authoritative snapshot did not complete within its bounds"
        )
    if (
        snapshot_authoritative
        and baseline
        and not versions
        and not allow_empty_snapshot
    ):
        raise GraphQLDocumentError(
            "GraphQL empty authoritative snapshot requires explicit approval"
        )


def _governance_state_dict(
    governance: tuple[
        ExternalAccess,
        DataClassification,
        str | None,
        bool,
        str,
        str,
        str,
    ],
) -> dict[str, Any]:
    (
        access,
        classification,
        retention,
        legal_hold,
        tenant,
        schema_version,
        mapping_version,
    ) = governance
    return {
        "access": access.model_dump(mode="json"),
        "classification": classification.value,
        "retention": retention,
        "legal_hold": legal_hold,
        "tenant": tenant,
        "schema_version": schema_version,
        "ontology_mapping_version": mapping_version,
    }


def _changed_node_ids(
    versions: dict[str, str],
    baseline: dict[str, str],
    prior_state: dict[str, Any],
    profile_digest: str,
    governance_state: dict[str, Any],
) -> set[str]:
    changed = {
        node_id
        for node_id, version in versions.items()
        if str(baseline.get(node_id) or "") != version
    }
    if prior_state and (
        prior_state.get("profile_digest") != profile_digest
        or prior_state.get("governance") != governance_state
    ):
        changed.update(versions)
    return changed


def _changed_entities(
    documents: list[SourceDocument],
    envelopes: list[GovernedChange],
    versions: dict[str, str],
    baseline: dict[str, str],
    prior_state: dict[str, Any],
    profile_digest: str,
    governance_state: dict[str, Any],
) -> tuple[set[str], list[SourceDocument], list[GovernedChange]]:
    changed = _changed_node_ids(
        versions, baseline, prior_state, profile_digest, governance_state
    )
    changed_documents = [
        document
        for document in documents
        if str(document.metadata.get("governed_entity_id") or "") in changed
    ]
    changed_envelopes = [envelope for envelope in envelopes if envelope.id in changed]
    return changed, changed_documents, changed_envelopes


@dataclass(frozen=True)
class _PreviousGovernance:
    """Governance recovered from the prior checkpoint, for tombstones."""

    access: ExternalAccess
    classification: DataClassification
    retention: str | None
    legal_hold: bool
    tenant: str
    schema_version: str
    mapping_version: str


def _parse_previous_governance_fields(
    previous_governance: Mapping[str, Any],
) -> _PreviousGovernance:
    try:
        previous_access = _access_from_config(previous_governance.get("access"))
        previous_classification = _classification(
            previous_governance.get("classification")
        )
        previous_retention = (
            str(previous_governance.get("retention") or "").strip() or None
        )
        previous_legal_hold = bool(previous_governance.get("legal_hold", False))
        previous_tenant = str(previous_governance.get("tenant") or "")
        previous_schema = str(previous_governance.get("schema_version") or "1")
        previous_mapping = str(
            previous_governance.get("ontology_mapping_version") or "1"
        )
    except (TypeError, ValueError, GraphQLDocumentError):
        raise GraphQLDocumentError(
            "GraphQL checkpoint governance state is invalid"
        ) from None
    return _PreviousGovernance(
        access=previous_access,
        classification=previous_classification,
        retention=previous_retention,
        legal_hold=previous_legal_hold,
        tenant=previous_tenant,
        schema_version=previous_schema,
        mapping_version=previous_mapping,
    )


def _resolve_previous_governance(
    previous_governance: Any,
) -> _PreviousGovernance:
    if not isinstance(previous_governance, Mapping):
        raise GraphQLDocumentError("GraphQL checkpoint governance state is invalid")
    fields = _parse_previous_governance_fields(previous_governance)
    if fields.tenant:
        _safe_alias(fields.tenant, label="tenant")
    if fields.retention and not _RETENTION_RE.fullmatch(fields.retention):
        raise GraphQLDocumentError("GraphQL checkpoint governance state is invalid")
    return fields


def _finalize_diagnostics(
    diagnostics: dict[str, Any],
    versions: dict[str, str],
    documents: list[SourceDocument],
    changed: set[str],
    changed_documents: list[SourceDocument],
    tombstones: list[GovernedChange],
) -> dict[str, Any]:
    return {
        **diagnostics,
        "entities": len(versions),
        "documents": len(documents),
        "changed_entities": len(changed),
        "changed_documents": len(changed_documents),
        "tombstones": len(tombstones),
    }
