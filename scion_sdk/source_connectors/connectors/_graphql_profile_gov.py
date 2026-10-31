"""Governance and discovery validation for GraphQL profiles."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._graphql_base import (
    _RETENTION_RE,
    _VERSION_LABEL_RE,
    GraphQLDocumentError,
)
from ._graphql_settings import _access_from_config
from ._graphql_values import _classification, _safe_alias


def _validate_governance_shape(governance: Any) -> None:
    if not isinstance(governance, dict):
        raise GraphQLDocumentError("GraphQL governance mapping is invalid")
    _classification(governance.get("classification"))
    if "legal_hold" in governance and not isinstance(governance["legal_hold"], bool):
        raise GraphQLDocumentError("GraphQL governance legal hold is invalid")


def _validate_governance_retention(governance: dict[str, Any], mappings: Any) -> str:
    retention = str(governance.get("retention") or "").strip()
    if mappings is not None and not retention:
        raise GraphQLDocumentError(
            "GraphQL hierarchy governance requires a retention policy"
        )
    if retention and not _RETENTION_RE.fullmatch(retention):
        raise GraphQLDocumentError("GraphQL governance retention is invalid")
    return retention


def _validate_governance_versions(governance: dict[str, Any]) -> None:
    tenant = str(governance.get("tenant") or "").strip()
    if tenant:
        _safe_alias(tenant, label="tenant")
    for key in ("schema_version", "ontology_mapping_version"):
        if key in governance and not _VERSION_LABEL_RE.fullmatch(
            str(governance[key] or "")
        ):
            raise GraphQLDocumentError("GraphQL governance version is invalid")


def _validate_governance(profile: dict[str, Any], mappings: Any) -> None:
    governance = profile.get("governance") or {}
    _validate_governance_shape(governance)
    _validate_governance_retention(governance, mappings)
    _validate_governance_versions(governance)
    _access_from_config(governance.get("access", profile.get("access")))


def _validate_discovery(profile: dict[str, Any]) -> None:
    discovery = profile.get("discovery")
    if discovery is not None and not isinstance(discovery, Mapping):
        raise GraphQLDocumentError("GraphQL discovery policy is invalid")
    if isinstance(discovery, Mapping):
        for key in ("enabled", "allow_introspection"):
            if key in discovery and not isinstance(discovery[key], bool):
                raise GraphQLDocumentError("GraphQL discovery policy is invalid")
