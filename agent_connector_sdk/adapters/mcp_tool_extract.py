"""Small extraction steps used by the MCP tool source adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceRecord,
    SourceRelationship,
)

from agent_connector_sdk.adapters.mcp_tool_lifecycle import (
    _record_mapping,
    _relation_reference,
    _source_relationship,
)
from agent_connector_sdk.adapters.mcp_tool_paging import (
    checkpoint_after_page,
    dig_path,
    next_position,
)
from agent_connector_sdk.adapters.mcp_tool_records import source_record
from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import SourceContractError


def _mapped_records(
    raw: Sequence[dict[str, Any]],
    *,
    connector: str,
    preset: ToolPreset,
    configured_mapping: str,
    mappings: Mapping[str, SchemaMapping],
    schema_sha256: str,
    since: str | None,
) -> tuple[tuple[SourceRecord, ...], dict[str, str]]:
    """Map raw objects and retain exact mappings by source id for edges."""
    references = {
        str(dig_path(item, preset.id_field)): _record_mapping(
            connector=connector,
            configured=configured_mapping,
            mappings=mappings,
            preset=preset,
            raw=item,
        )
        for item in raw
    }
    records = tuple(
        record
        for item in raw
        if not (
            since
            and (updated := dig_path(item, preset.updated_field)) is not None
            and str(updated) <= since
        )
        for record in (
            source_record(
                preset,
                item,
                connector=connector,
                schema_sha256=schema_sha256,
                mapping_reference=references[str(dig_path(item, preset.id_field))],
            ),
        )
    )
    return records, references


def _page_checkpoint(
    preset: ToolPreset,
    current: SourceCheckpoint,
    records: Sequence[SourceRecord],
    *,
    result: Any,
    raw: Sequence[dict[str, Any]],
) -> tuple[SourceCheckpoint, bool]:
    """Return the provider checkpoint and whether pagination exhausted."""
    position = current.position if isinstance(current.position, Mapping) else {}
    next_page = next_position(preset, position, result=result, raw=raw)
    provider_position = (
        dig_path(result, preset.checkpoint_path)
        if preset.checkpoint_path
        else next_page
    )
    if preset.checkpoint_path and provider_position is None:
        raise SourceContractError("provider response omitted its checkpoint")
    content_hash = (
        dig_path(result, preset.content_hash_path) if preset.content_hash_path else None
    )
    if content_hash is not None and not isinstance(content_hash, str):
        raise SourceContractError("provider content_hash is not a string")
    return (
        checkpoint_after_page(
            current, records, provider_position, content_hash=content_hash
        ),
        next_page is None,
    )


def _mapped_relationships(
    raw: Sequence[dict[str, Any]],
    *,
    connector: str,
    preset: ToolPreset,
    mappings: Mapping[str, SchemaMapping],
    resources: Mapping[str, ResourceSpec],
    mappings_by_id: Mapping[str, str],
    schema_sha256: str,
) -> tuple[SourceRelationship, ...]:
    """Map provider edges under exact manifest relation references."""
    return tuple(
        _source_relationship(
            preset,
            edge,
            connector=connector,
            schema_sha256=schema_sha256,
            relation_reference=_relation_reference(
                connector=connector,
                mappings=mappings,
                resources=resources,
                preset=preset,
                raw=edge,
                mappings_by_id=mappings_by_id,
            ),
        )
        for edge in raw
    )
