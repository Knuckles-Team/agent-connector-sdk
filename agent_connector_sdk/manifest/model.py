"""The Connector Ontology Manifest schema (``connector_manifest.yml``).

Extracted from ``agent_utilities.knowledge_graph.ontology.connector_manifest``:
the Pydantic models every connector's manifest validates against. The manifest
*generator* heuristics (hub-class crosswalk, PII field-name guesses) and the
OWL compiler dataclasses stay with the tooling that generates and compiles
manifests; they are not part of the schema.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ActionParameterSpec",
    "ActionSpec",
    "ConnectorManifest",
    "EventSpec",
    "IdentitySpec",
    "IntegrityInfo",
    "PermissionsSpec",
    "PolicySpec",
    "ProvenanceSpec",
    "ResourceRelation",
    "ResourceSpec",
    "SchemaMapping",
    "SyncSpec",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceRelation(_Strict):
    """One outgoing relation from a resource (an OWL object property)."""

    name: str
    label: str = ""
    target: str
    lpg_rel_type: str = ""


class SchemaMapping(_Strict):
    """How one resource's fields map onto the canonical ontology."""

    ontology_class: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class ResourceSpec(_Strict):
    """One connector resource (a record kind)."""

    name: str
    label: str = ""
    id_prefix: str = ""
    relations: list[ResourceRelation] = Field(default_factory=list)


class ActionParameterSpec(_Strict):
    """One typed input parameter of a declared action."""

    name: str
    type: str = "string"
    required: bool = True
    description: str = ""


_DESTRUCTIVE_ACTION_TERMS: frozenset[str] = frozenset(
    {
        "clear",
        "deactivate",
        "delete",
        "destroy",
        "drop",
        "evict",
        "invalidate",
        "prune",
        "purge",
        "remove",
        "revoke",
        "terminate",
        "uninstall",
        "unref",
        "wipe",
    }
)


class ActionSpec(_Strict):
    """One connector action, optionally declared as a governed mutating write."""

    id: str
    name: str = ""
    description: str = ""
    label: str = ""
    parameters: list[ActionParameterSpec] = Field(default_factory=list)
    target_resource: str | None = None
    conflict_policy: (
        Literal["source_wins", "graph_derived", "manual_review", "reject"] | None
    ) = None
    requires_approval: bool = True
    approval_class: str = "unclassified"
    effects: list[str] = Field(default_factory=list)


class EventSpec(_Strict):
    """One connector-emitted event (typically a watermark event)."""

    name: str
    resource: str = ""
    description: str = ""


class IdentitySpec(_Strict):
    """Per-resource record identity fields."""

    id_field: dict[str, str] = Field(default_factory=dict)
    title_field: dict[str, str] = Field(default_factory=dict)
    text_field: dict[str, str] = Field(default_factory=dict)
    updated_field: dict[str, str] = Field(default_factory=dict)


class PermissionsSpec(_Strict):
    """Access-control and tenant-scoping fields."""

    acl_fields: list[str] = Field(default_factory=list)
    tenant_field: str | None = None
    read_roles: list[str] = Field(default_factory=list)


class SyncSpec(_Strict):
    """One declared sync preset, with the full preset carried in ``raw``."""

    preset: str
    server: str
    tool: str
    action: str | None = None
    records_path: str | None = None
    id_field: str | None = None
    title_field: str | None = None
    text_field: str | None = None
    updated_field: str | None = None
    pagination: str | None = None
    doc_type: str | None = None
    tool_schema_sha256: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class IntegrityInfo(_Strict):
    """Canonical-graph hash of the connector ontology."""

    algorithm: str = "urdna2015-sha256"
    hash: str
    triple_count: int = 0


class ProvenanceSpec(_Strict):
    """Who generated the manifest, and its integrity pin."""

    generated_by: str = "scripts/generate_connector_manifests.py"
    generated_at: str = ""
    source_artifacts: list[str] = Field(default_factory=list)
    integrity: IntegrityInfo
    signer: str | None = None
    signature_algorithm: str | None = None
    signing_public_key: str | None = None
    signature: str | None = None
    source_commit: str | None = None


class PolicySpec(_Strict):
    """Row-level security, tenant boundary and PII declarations."""

    pii_fields: dict[str, list[str]] = Field(default_factory=dict)
    tenant_boundary: str | None = None
    rls: list[str] = Field(default_factory=list)


class ConnectorManifest(_Strict):
    """The full manifest: ``agents/<package>/connector_manifest.yml``."""

    connector: str
    ontology_source: str = ""
    schema_version: str = "1"
    resources: list[ResourceSpec] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(default_factory=list)
    events: list[EventSpec] = Field(default_factory=list)
    identity: IdentitySpec = Field(default_factory=IdentitySpec)
    permissions: PermissionsSpec = Field(default_factory=PermissionsSpec)
    schema_mappings: dict[str, SchemaMapping] = Field(default_factory=dict)
    sync: list[SyncSpec] = Field(default_factory=list)
    provenance: ProvenanceSpec
    policy: PolicySpec = Field(default_factory=PolicySpec)
    review_todos: list[str] = Field(default_factory=list)

    @property
    def resolved_ontology_source(self) -> str:
        """``ontology_source`` when set, otherwise ``connector``."""
        return self.ontology_source or self.connector

    @model_validator(mode="after")
    def _check_actions_resolve(self) -> ConnectorManifest:
        """Actions must target declared resources and cannot silently skip approval."""
        resource_names = {resource.name for resource in self.resources}
        for action in self.actions:
            if (
                action.target_resource is not None
                and action.target_resource not in resource_names
            ):
                raise ValueError(
                    f"action {action.id!r} target_resource "
                    f"{action.target_resource!r} does not name a resources[].name "
                    "in this manifest"
                )
            if action.requires_approval is False:
                words = set(
                    re.findall(r"[a-z0-9]+", f"{action.id} {action.name}".lower())
                )
                hit = words & _DESTRUCTIVE_ACTION_TERMS
                if hit:
                    raise ValueError(
                        f"action {action.id!r} sets requires_approval: false but "
                        f"its id/name contains destructive term(s) {sorted(hit)!r}"
                    )
        return self
