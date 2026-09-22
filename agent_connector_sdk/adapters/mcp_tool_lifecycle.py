"""Lifecycle mapping for generated SourceIngest entities and relationships."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceEntityRef,
    SourceIngestionMode,
    SourceRecordProvenance,
    SourceRelationship,
    SourceWithdrawal,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from agent_connector_sdk.adapters.mcp_tool_paging import dig_path
from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def raw_relationships(preset: ToolPreset, result: Any) -> list[dict[str, Any]]:
    """Return every declared top-level relationship without dropping fields."""
    if not preset.relationships_path:
        return []
    data = dig_path(result, preset.relationships_path)
    if not isinstance(data, list) or not all(
        isinstance(item, Mapping) for item in data
    ):
        raise MalformedSourceDataError(
            f"response does not match relationships_path {preset.relationships_path!r}"
        )
    relationships = [dict(item) for item in data]
    for relationship in relationships:
        for path, label in (
            (preset.relationship_source_field, "source"),
            (preset.relationship_target_field, "target"),
            (preset.relationship_type_field, "type"),
        ):
            value = dig_path(relationship, path)
            if value in (None, "") or isinstance(value, dict | list):
                raise MalformedSourceDataError(
                    f"relationship has no usable {label} at {path!r}"
                )
    return relationships


def _entity_ref(value: Any, *, stream: str, label: str) -> SourceEntityRef:
    if isinstance(value, Mapping):
        ref_stream = value.get("stream", stream)
        record_id = value.get("record_id", value.get("id"))
    else:
        ref_stream, record_id = stream, value
    if (
        ref_stream in (None, "")
        or record_id in (None, "")
        or isinstance(ref_stream, dict | list)
        or isinstance(record_id, dict | list)
    ):
        raise MalformedSourceDataError(f"relationship has no usable {label}")
    return SourceEntityRef(stream=str(ref_stream), record_id=str(record_id))


def _source_relationship(
    preset: ToolPreset,
    raw: dict[str, Any],
    *,
    connector: str,
    schema_sha256: str,
    relation_reference: str,
) -> SourceRelationship:
    """Map one provider edge without inventing its durable identity."""
    source = _entity_ref(
        dig_path(raw, preset.relationship_source_field),
        stream=preset.name,
        label="source",
    )
    target = _entity_ref(
        dig_path(raw, preset.relationship_target_field),
        stream=preset.name,
        label="target",
    )
    properties: dict[str, JsonValue] | None = None
    if preset.relationship_properties_field:
        try:
            properties = _JSON_OBJECT.validate_python(
                dig_path(raw, preset.relationship_properties_field)
            )
        except ValidationError as exc:
            raise MalformedSourceDataError(
                "relationship properties are not a JSON object"
            ) from exc
    return SourceRelationship(
        source=source,
        target=target,
        relation_reference=relation_reference,
        properties=properties,
        provenance=SourceRecordProvenance(
            connector=connector,
            adapter_kind="mcp_tool",
            server=preset.server,
            tool=preset.tool,
            tool_schema_sha256=schema_sha256,
            source_uri=(
                f"mcp-tool://{preset.server}/{preset.tool}/relationships/"
                f"{source.record_id}/{target.record_id}"
            ),
        ),
    )


def authoritative_live_ids(
    preset: ToolPreset, result: Any
) -> tuple[SourceEntityRef, ...] | None:
    """Return a complete provider live set only when it declares authority."""
    if not preset.authoritative_path:
        return None
    if dig_path(result, preset.authoritative_path) is not True:
        return None
    values = dig_path(result, preset.reconcile_path)
    if not isinstance(values, list):
        raise MalformedSourceDataError("authoritative live ids are not a list")
    return tuple(
        _entity_ref(value, stream=preset.name, label="live id") for value in values
    )


def _source_withdrawals(
    preset: ToolPreset, result: Any
) -> tuple[SourceWithdrawal, ...]:
    """Return explicit provider-declared delta withdrawals."""
    if not preset.withdrawals_path:
        return ()
    values = dig_path(result, preset.withdrawals_path)
    if not isinstance(values, list) or not all(
        isinstance(value, Mapping) for value in values
    ):
        raise MalformedSourceDataError("withdrawals are not a list of objects")
    withdrawals: list[SourceWithdrawal] = []
    for value in values:
        entity = _entity_ref(
            dig_path(value, preset.withdrawal_id_field),
            stream=preset.name,
            label="withdrawal id",
        )
        reason = dig_path(value, preset.withdrawal_reason_field)
        if not isinstance(reason, str) or not reason.strip():
            raise MalformedSourceDataError("withdrawal has no usable reason")
        withdrawals.append(SourceWithdrawal(entity=entity, reason=reason))
    return tuple(withdrawals)


def _record_mapping(
    *,
    connector: str,
    configured: str,
    mappings: Mapping[str, SchemaMapping],
    preset: ToolPreset,
    raw: dict[str, Any],
) -> str:
    """Resolve the authoring shorthand to one exact manifest mapping."""
    prefix = f"manifest:{connector}#schema_mappings/"
    if configured.startswith(prefix):
        return configured
    if configured != f"manifest:{connector}":
        raise SourceContractError(
            "mapping_reference is not an exact Connector Manifest mapping"
        )
    key = (
        next(iter(mappings))
        if len(mappings) == 1
        else dig_path(raw, preset.node_type_field)
    )
    if not isinstance(key, str) or key not in mappings:
        raise SourceContractError("record type has no exact manifest mapping")
    return f"{prefix}{key}"


def _relation_reference(
    *,
    connector: str,
    mappings: Mapping[str, SchemaMapping],
    resources: Mapping[str, ResourceSpec],
    preset: ToolPreset,
    raw: dict[str, Any],
    mappings_by_id: Mapping[str, str],
) -> str:
    """Resolve an edge to its declaring manifest resource and predicate."""
    source_id = dig_path(raw, preset.relationship_source_field)
    if isinstance(source_id, Mapping):
        source_id = source_id.get("record_id", source_id.get("id"))
    prefix = f"manifest:{connector}#schema_mappings/"
    mapping_reference = mappings_by_id.get(str(source_id))
    if mapping_reference is None or not mapping_reference.startswith(prefix):
        raise SourceContractError(
            "relationship source has no manifest mapping in this page"
        )
    key = mapping_reference.removeprefix(prefix)
    mapping = mappings.get(key)
    resource_name = mapping.ontology_class if mapping else key
    resource = resources.get(resource_name) if resource_name is not None else None
    relation = dig_path(raw, preset.relationship_type_field)
    if (
        resource is None
        or not isinstance(relation, str)
        or not any(declared.name == relation for declared in resource.relations)
    ):
        raise SourceContractError(
            "relationship predicate is not declared by its manifest resource"
        )
    return f"manifest:{connector}#resources/{resource.name}/relations/{relation}"


def _ingestion_mode(
    preset: ToolPreset,
    *,
    result: Any,
    live_ids: Sequence[SourceEntityRef] | None,
    checkpoint: SourceCheckpoint | None,
) -> SourceIngestionMode:
    """Choose explicit provider mode, reconciliation, or incremental delta."""
    if live_ids is not None:
        return SourceIngestionMode.RECONCILE
    configured = dig_path(preset.params, preset.mode_param)
    if configured is None:
        return (
            SourceIngestionMode.DELTA
            if checkpoint is not None and preset.updated_since_param
            else SourceIngestionMode.FULL
        )
    try:
        mode = SourceIngestionMode(str(configured))
    except ValueError as exc:
        raise SourceContractError(
            f"provider configured unsupported ingestion mode {configured!r}"
        ) from exc
    if mode is SourceIngestionMode.RECONCILE:
        raise SourceContractError(
            "reconcile response did not declare an authoritative live set"
        )
    return mode
