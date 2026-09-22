"""Turn an ``mcp_tool`` result into validated source records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceRecord,
    SourceRecordProvenance,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from agent_connector_sdk.adapters.mcp_tool_lifecycle import raw_relationships
from agent_connector_sdk.adapters.mcp_tool_paging import dig_path
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import MalformedSourceDataError

__all__ = ["raw_records", "raw_relationships", "source_record"]

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def _mapping_records(
    preset: ToolPreset, data: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if not all(isinstance(value, Mapping) for value in data.values()):
        raise MalformedSourceDataError("mapping holds a non-object record")
    return [
        {preset.mapping_key_field: str(key), **dict(value)}
        for key, value in data.items()
    ]


def raw_records(preset: ToolPreset, result: Any) -> list[dict[str, Any]]:
    """Return the object records selected by the preset."""
    data = dig_path(result, preset.records_path) if preset.records_path else result
    if isinstance(data, Mapping) and preset.records_is_mapping:
        return _mapping_records(preset, data)
    if not isinstance(data, list):
        raise MalformedSourceDataError(
            f"response does not match records_path {preset.records_path!r}"
        )
    if not all(isinstance(item, Mapping) for item in data):
        raise MalformedSourceDataError("response holds a non-object record")
    return [dict(item) for item in data]


def _record_id(preset: ToolPreset, raw: dict[str, Any]) -> object:
    record_id = dig_path(raw, preset.id_field)
    if record_id in (None, "") or isinstance(record_id, dict | list):
        raise MalformedSourceDataError(
            f"record has no usable id at {preset.id_field!r}"
        )
    return record_id


def _validate_strict_fields(preset: ToolPreset, raw: dict[str, Any]) -> None:
    if not preset.strict_schema:
        return
    allowed = frozenset((*preset.metadata_fields, *preset.content_fields))
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise MalformedSourceDataError(
            f"record has fields outside its strict schema: {', '.join(unknown)}"
        )


def _validate_node_type(preset: ToolPreset, raw: dict[str, Any]) -> None:
    if preset.record_mode != "typed_entities":
        return
    node_type = dig_path(raw, preset.node_type_field)
    if node_type in (None, "") or isinstance(node_type, dict | list):
        raise MalformedSourceDataError(
            f"record has no usable node type at {preset.node_type_field!r}"
        )


def source_record(
    preset: ToolPreset,
    raw: dict[str, Any],
    *,
    connector: str,
    schema_sha256: str,
    mapping_reference: str,
) -> SourceRecord:
    """Return one generated record with exact mapping and provenance."""
    record_id = _record_id(preset, raw)
    _validate_strict_fields(preset, raw)
    _validate_node_type(preset, raw)
    updated = dig_path(raw, preset.updated_field) if preset.updated_field else None
    provenance = SourceRecordProvenance(
        connector=connector,
        adapter_kind="mcp_tool",
        server=preset.server,
        tool=preset.tool,
        tool_schema_sha256=schema_sha256,
        source_uri=f"mcp-tool://{preset.server}/{preset.tool}/{record_id}",
    )
    try:
        payload = _JSON_OBJECT.validate_python(raw)
        return SourceRecord(
            stream=preset.name,
            record_id=str(record_id),
            mapping_reference=mapping_reference,
            payload=payload,
            updated_at=None if updated is None else str(updated),
            provenance=provenance,
        )
    except ValidationError as exc:
        raise MalformedSourceDataError("record payload is not JSON data") from exc
