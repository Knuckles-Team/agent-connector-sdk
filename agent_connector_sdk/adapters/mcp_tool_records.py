"""Turn an ``mcp_tool`` result into validated source records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agent_connector_sdk.adapters.mcp_tool_paging import dig_path
from agent_connector_sdk.contracts import RecordProvenance, SourceRecord
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import MalformedSourceDataError

__all__ = ["raw_records", "source_record"]


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
    """The records at ``records_path``.

    Raises:
        MalformedSourceDataError: the path holds neither a list of objects nor,
            for a mapping preset, a mapping of objects.
    """
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


def source_record(
    preset: ToolPreset, raw: dict[str, Any], *, connector: str, schema_sha256: str
) -> SourceRecord:
    """One validated record with complete provenance.

    Raises:
        MalformedSourceDataError: no usable id, or a payload that is not JSON.
    """
    record_id = dig_path(raw, preset.id_field)
    if record_id in (None, "") or isinstance(record_id, dict | list):
        raise MalformedSourceDataError(
            f"record has no usable id at {preset.id_field!r}"
        )
    updated = dig_path(raw, preset.updated_field) if preset.updated_field else None
    provenance = RecordProvenance(
        connector=connector,
        adapter_kind="mcp_tool",
        server=preset.server,
        tool=preset.tool,
        tool_schema_sha256=schema_sha256,
        source_uri=f"mcp-tool://{preset.server}/{preset.tool}/{record_id}",
    )
    try:
        return SourceRecord(
            stream=preset.name,
            record_id=str(record_id),
            payload=raw,
            updated_at=None if updated is None else str(updated),
            provenance=provenance,
        )
    except ValidationError as exc:
        raise MalformedSourceDataError("record payload is not JSON data") from exc
