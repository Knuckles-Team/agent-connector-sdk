"""Entity-mapping validation for GraphQL profiles."""

from __future__ import annotations

from typing import Any

from ._graphql_base import (
    _MAPPING_KEYS,
    GraphQLDocumentError,
)
from ._graphql_paths import _valid_field_path


def _validate_entity_mapping_paths(mapping: dict[str, Any]) -> None:
    id_path = str(mapping.get("id_path") or "id")
    if not _valid_field_path(id_path):
        raise GraphQLDocumentError("GraphQL entity identity mapping is invalid")
    records_path = str(mapping.get("records_path") or "")
    if records_path and not _valid_field_path(records_path):
        raise GraphQLDocumentError("GraphQL entity records mapping is invalid")
    if any(
        not _valid_field_path(value)
        for key, value in mapping.items()
        if key.endswith("_path") and value not in (None, "")
    ):
        raise GraphQLDocumentError("GraphQL entity field path is invalid")


def _validate_entity_allowlist(mapping: dict[str, Any]) -> None:
    allowlist = mapping.get("property_allowlist")
    if not isinstance(allowlist, list) or len(allowlist) > 256:
        raise GraphQLDocumentError("GraphQL entity property allowlist is required")
    if any(not _valid_field_path(field) for field in allowlist):
        raise GraphQLDocumentError("GraphQL entity property allowlist is invalid")


def _validate_hierarchy_children_path(mapping: dict[str, Any]) -> None:
    children_path = str(mapping.get("children_path") or "")
    if children_path and not _valid_field_path(children_path):
        raise GraphQLDocumentError("GraphQL hierarchy children mapping is invalid")


def _validate_entity_mapping(kind: str, mapping: Any) -> None:
    if not isinstance(mapping, dict):
        raise GraphQLDocumentError("GraphQL entity mapping is invalid")
    _validate_entity_mapping_paths(mapping)
    _validate_entity_allowlist(mapping)
    if kind == "hierarchy":
        _validate_hierarchy_children_path(mapping)


def _validate_snapshot_authority_flags(op: dict[str, Any]) -> None:
    for key in ("snapshot_authoritative", "allow_empty_snapshot"):
        if key in op and not isinstance(op[key], bool):
            raise GraphQLDocumentError("GraphQL snapshot authority policy is invalid")
    if op.get("allow_empty_snapshot") is True and not op.get(
        "snapshot_authoritative", False
    ):
        raise GraphQLDocumentError(
            "GraphQL empty snapshot approval requires authoritative mode"
        )


def _validate_mappings(mappings: Any) -> None:
    if not isinstance(mappings, dict):
        raise GraphQLDocumentError("GraphQL entity mappings are invalid")
    recognized = False
    for kind, aliases in _MAPPING_KEYS.items():
        mapping = next(
            (mappings.get(alias) for alias in aliases if alias in mappings),
            None,
        )
        if mapping is None:
            continue
        recognized = True
        _validate_entity_mapping(kind, mapping)
    if not recognized:
        raise GraphQLDocumentError("GraphQL profile has no entity mappings")


def _validate_snapshot_policy_and_mappings(op: dict[str, Any]) -> Any:
    mappings = op.get("mappings")
    _validate_snapshot_authority_flags(op)
    if mappings is not None:
        _validate_mappings(mappings)
    return mappings
