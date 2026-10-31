"""Snapshot reconciliation collaborator for the GraphQL document connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scion_sdk.data_prep._classification import DataClassification

from ..base import (
    ConnectorCheckpoint,
    ExternalAccess,
    SourceDocument,
)
from ._graphql_base import (
    _CHECKPOINT_FORMAT,
    GraphQLDocumentError,
)
from ._graphql_change import GovernedChange, GraphQLHierarchyBatch, _governed_change
from ._graphql_snapshot_state import (
    _changed_entities,
    _finalize_diagnostics,
    _governance_state_dict,
    _PreviousGovernance,
    _resolve_previous_governance,
    _validate_checkpoint_sequence,
    _validate_snapshot_completeness,
)
from ._graphql_values import (
    _digest,
)


@dataclass(frozen=True)
class _SnapshotReconciler:
    """Diff a fetched snapshot against the prior checkpoint into a batch."""

    source_alias: str
    operation: str
    max_entities: int
    max_documents: int

    def _validate_checkpoint_scope(self, prior_state: dict[str, Any]) -> None:
        if prior_state and prior_state.get("checkpoint_format") != _CHECKPOINT_FORMAT:
            raise GraphQLDocumentError("GraphQL checkpoint format is invalid")
        if prior_state and (
            prior_state.get("source_alias") != self.source_alias
            or prior_state.get("operation") != self.operation
        ):
            raise GraphQLDocumentError("GraphQL checkpoint scope is invalid")

    def _validate_checkpoint_baseline(
        self, prior_state: dict[str, Any]
    ) -> dict[str, str]:
        baseline_raw = prior_state.get("versions")
        baseline = baseline_raw if isinstance(baseline_raw, dict) else {}
        if len(baseline) > max(self.max_entities, self.max_documents) or any(
            not isinstance(node_id, str)
            or not isinstance(version, str)
            or not node_id
            or not version
            for node_id, version in baseline.items()
        ):
            raise GraphQLDocumentError("GraphQL checkpoint state is invalid")
        return baseline

    def _load_prior_checkpoint_state(
        self, checkpoint: ConnectorCheckpoint | None
    ) -> tuple[dict[str, Any], dict[str, str], int]:
        prior_state = checkpoint.state if checkpoint else {}
        self._validate_checkpoint_scope(prior_state)
        baseline = self._validate_checkpoint_baseline(prior_state)
        prior_sequence = _validate_checkpoint_sequence(prior_state)
        return prior_state, baseline, prior_sequence

    def _tombstone_for_node(
        self,
        node_id: str,
        baseline: dict[str, str],
        next_snapshot_digest: str,
        previous_fields: _PreviousGovernance,
        prior_state: dict[str, Any],
        versions: dict[str, str],
        allow_empty_snapshot: bool,
    ) -> GovernedChange:
        previous = previous_fields
        delete_version = _digest(
            "graphql-snapshot-delete",
            baseline[node_id],
            next_snapshot_digest,
        )
        return _governed_change(
            operation="delete",
            tenant=previous.tenant,
            source_instance=self.source_alias,
            source_object_id=node_id,
            source_version=delete_version,
            schema_version=previous.schema_version,
            ontology_mapping_version=previous.mapping_version,
            source_acl=previous.access,
            classification=previous.classification,
            retention=previous.retention,
            legal_hold=previous.legal_hold,
            provenance={
                "profile_digest": str(prior_state.get("profile_digest") or ""),
                "privacy_gate": True,
                "identity_scheme": "hmac-sha256",
                "snapshot_reconciliation": True,
                "authoritative_empty_approved": bool(
                    not versions and allow_empty_snapshot
                ),
            },
            checkpoint=delete_version,
        )

    def _build_tombstones(
        self,
        baseline: dict[str, str],
        versions: dict[str, str],
        prior_state: dict[str, Any],
        snapshot_authoritative: bool,
        allow_empty_snapshot: bool,
        prior_sequence: int,
    ) -> list[GovernedChange]:
        missing = sorted(set(baseline).difference(versions))
        if not (snapshot_authoritative and missing):
            return []
        previous_governance = prior_state.get("governance")
        previous_fields = _resolve_previous_governance(previous_governance)
        next_snapshot_digest = _digest(
            self.source_alias,
            self.operation,
            prior_sequence + 1,
            sorted(versions.items()),
        )
        return [
            self._tombstone_for_node(
                node_id,
                baseline,
                next_snapshot_digest,
                previous_fields,
                prior_state,
                versions,
                allow_empty_snapshot,
            )
            for node_id in missing
        ]

    def _build_next_checkpoint(
        self,
        prior_state: dict[str, Any],
        baseline: dict[str, str],
        versions: dict[str, str],
        profile_digest: str,
        governance_state: dict[str, Any],
        snapshot_authoritative: bool,
        allow_empty_snapshot: bool,
        prior_sequence: int,
    ) -> ConnectorCheckpoint:
        checkpoint_changed = not prior_state or any(
            (
                baseline != versions,
                prior_state.get("profile_digest") != profile_digest,
                prior_state.get("governance") != governance_state,
                prior_state.get("snapshot_authoritative") != snapshot_authoritative,
                prior_state.get("allow_empty_snapshot") != allow_empty_snapshot,
            )
        )
        sequence = prior_sequence + int(checkpoint_changed)
        watermark = _digest(
            self.source_alias,
            self.operation,
            sequence,
            sorted(versions.items()),
        )
        return ConnectorCheckpoint(
            has_more=False,
            watermark=watermark,
            seen_ids=sorted(versions)[-self.max_entities :],
            state={
                "checkpoint_format": _CHECKPOINT_FORMAT,
                "source_alias": self.source_alias,
                "operation": self.operation,
                "profile_digest": profile_digest,
                "snapshot_sequence": sequence,
                "snapshot_authoritative": snapshot_authoritative,
                "allow_empty_snapshot": allow_empty_snapshot,
                "governance": governance_state,
                "versions": dict(sorted(versions.items())),
            },
        )

    def reconcile(
        self,
        *,
        documents: list[SourceDocument],
        envelopes: list[GovernedChange],
        versions: dict[str, str],
        checkpoint: ConnectorCheckpoint | None,
        profile_digest: str,
        diagnostics: dict[str, Any],
        governance: tuple[
            ExternalAccess,
            DataClassification,
            str | None,
            bool,
            str,
            str,
            str,
        ],
        snapshot_authoritative: bool,
        allow_empty_snapshot: bool,
    ) -> GraphQLHierarchyBatch:
        prior_state, baseline, prior_sequence = self._load_prior_checkpoint_state(
            checkpoint
        )
        _validate_snapshot_completeness(
            diagnostics,
            snapshot_authoritative,
            baseline,
            versions,
            allow_empty_snapshot,
        )
        governance_state = _governance_state_dict(governance)
        changed, changed_documents, changed_envelopes = _changed_entities(
            documents,
            envelopes,
            versions,
            baseline,
            prior_state,
            profile_digest,
            governance_state,
        )
        tombstones = self._build_tombstones(
            baseline,
            versions,
            prior_state,
            snapshot_authoritative,
            allow_empty_snapshot,
            prior_sequence,
        )
        next_checkpoint = self._build_next_checkpoint(
            prior_state,
            baseline,
            versions,
            profile_digest,
            governance_state,
            snapshot_authoritative,
            allow_empty_snapshot,
            prior_sequence,
        )
        diagnostics = _finalize_diagnostics(
            diagnostics, versions, documents, changed, changed_documents, tombstones
        )
        return GraphQLHierarchyBatch(
            documents=tuple(changed_documents),
            envelopes=tuple((*changed_envelopes, *tombstones)),
            checkpoint=next_checkpoint,
            diagnostics=diagnostics,
        )
