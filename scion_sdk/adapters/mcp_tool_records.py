"""Turn an ``mcp_tool`` result into validated source records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import anyio
from epistemic_graph.generated.source_ingestion import (
    SourceRecord,
    SourceRecordProvenance,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from scion_sdk.adapters._platform_validation import (
    _bounded_json,
    _validate_source_binding,
)
from scion_sdk.adapters.mcp_tool_lifecycle import raw_relationships
from scion_sdk.adapters.mcp_tool_paging import dig_path
from scion_sdk.adapters.platform_models import PlatformResult
from scion_sdk.manifest.presets import ToolPreset
from scion_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from scion_sdk.vendor_extractors.enterprise_contract import (
    CreateInvoice,
    EnterpriseOperation,
    EnterpriseResult,
)
from scion_sdk.vendor_extractors.enterprise_dispatch import _operation_digest

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


async def _validate_platform_binding(
    preset: ToolPreset, arguments: dict[str, Any], result: Any
) -> None:
    if preset.result_contract == "enterprise":
        try:
            await anyio.to_thread.run_sync(
                _validate_enterprise_source,
                preset,
                arguments,
                result,
                abandon_on_cancel=True,
            )
        except (KeyError, TypeError, ValueError):
            raise SourceContractError(
                "enterprise result does not match the source request"
            ) from None
        return
    if preset.result_contract != "platform":
        return
    binding_failed = False
    try:
        await anyio.to_thread.run_sync(
            _validate_source_binding, arguments, result, abandon_on_cancel=True
        )
    except (TypeError, ValueError):
        binding_failed = True
    if binding_failed:
        raise SourceContractError("platform result does not match the source request")


def _validate_enterprise_source(
    preset: ToolPreset, arguments: dict[str, Any], result: Any
) -> None:
    request = EnterpriseOperation.model_validate_json(
        _bounded_json(arguments["request"])
    )
    response = EnterpriseResult.model_validate_json(_bounded_json(result))
    if (
        isinstance(request.parameters, CreateInvoice)
        or response.request_id != request.request_id
        or response.tenant != request.tenant
        or response.company_id != request.company_id
        or response.connector != preset.server
        or response.contract_revision != request.contract_revision
        or response.operation != request.parameters.operation
        or response.operation_digest != _operation_digest(request)
    ):
        raise ValueError("enterprise binding mismatch")


def raw_records(preset: ToolPreset, result: Any) -> list[dict[str, Any]]:
    """Return the object records selected by the preset."""
    if preset.result_contract == "platform":
        platform_result = None
        try:
            platform_result = PlatformResult.model_validate_json(
                json.dumps(result, allow_nan=False)
            )
        except (TypeError, ValueError):
            platform_result = None
        if platform_result is None:
            raise MalformedSourceDataError("platform result is malformed")
        if platform_result.outcome == "refused":
            raise SourceContractError(
                f"platform result refused: {platform_result.reason}"
            )
        if platform_result.tenant_id is None or platform_result.policy_revision is None:
            raise MalformedSourceDataError(
                "platform result is missing authority or policy binding"
            )
    if preset.result_contract == "enterprise":
        try:
            enterprise = EnterpriseResult.model_validate_json(_bounded_json(result))
        except (TypeError, ValueError):
            raise MalformedSourceDataError("enterprise result is malformed") from None
        if enterprise.outcome != "ok":
            raise SourceContractError(f"enterprise result refused: {enterprise.reason}")
        if not enterprise.operation_digest or not enterprise.backend_receipt:
            raise MalformedSourceDataError("enterprise result lacks source evidence")
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
