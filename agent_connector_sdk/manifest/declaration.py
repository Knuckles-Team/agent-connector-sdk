"""The connector declaration, read from the server (``connector://resources``).

SDK-CONNECTOR-CONTROL-R075: a connector declares its data sources, runner
sync presets, record-type mappings and resources in code. The server serves
them; tool fingerprints are read from the live MCP handshake.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from agent_connector_sdk.ingest.sources import (
    IngestSourceDeclaration,
    IngestSourceSpec,
)
from agent_connector_sdk.manifest.model import (
    ResourceSpec,
    SchemaMapping,
    SyncSpec,
)
from agent_connector_sdk.manifest.presets import ToolPreset

__all__ = [
    "ContractError",
    "SyncContract",
    "contract_from_declaration",
    "contract_from_document",
]


class ContractError(ValueError):
    """A live declaration is invalid."""


@dataclass(frozen=True)
class SyncContract:
    """What the runner needs to sync one connector."""

    connector: str
    sync: tuple[SyncSpec, ...]
    schema_mappings: Mapping[str, SchemaMapping]
    resources: tuple[ResourceSpec, ...]


def _raw_preset(source: IngestSourceSpec, connector: str) -> dict[str, Any]:
    set_fields = source.model_fields_set
    renamed = {"cursor_field": "updated_field"}
    raw: dict[str, Any] = {
        "server": source.server or connector,
        "tool": source.tools[0],
        "id_field": source.id_field,
    }
    for name in (
        "records_path",
        "title_field",
        "text_field",
        "cursor_field",
        "pagination",
        "page_param",
        "page_size_param",
        "page_size",
        "start_page",
        "arguments",
    ):
        if name in set_fields:
            raw[renamed.get(name, name)] = getattr(source, name)
    if source.for_each is not None:
        raw["for_each"] = source.for_each.model_dump()
    raw.update(source.preset or {})
    return {key: value for key, value in raw.items() if value is not None}


def _sync_spec(source: IngestSourceSpec, connector: str) -> SyncSpec:
    raw = _raw_preset(source, connector)
    try:
        preset = ToolPreset.from_mapping(source.source_id, dict(raw))
    except ValidationError as exc:
        reasons = "; ".join(str(e["msg"]) for e in exc.errors())
        raise ContractError(
            f"source {source.source_id!r} is invalid: {reasons}"
        ) from exc
    return SyncSpec(
        preset=source.source_id,
        server=preset.server,
        tool=preset.tool,
        action=preset.action or None,
        records_path=preset.records_path,
        id_field=preset.id_field,
        title_field=preset.title_field,
        text_field=preset.text_field,
        updated_field=preset.updated_field,
        pagination=preset.pagination,
        doc_type=preset.doc_type,
        raw=raw,
    )


def contract_from_declaration(
    declaration: IngestSourceDeclaration,
) -> SyncContract | None:
    """The runner contract of a declaration, or ``None`` when no source has a preset."""
    sources = [s for s in declaration.sources if s.preset is not None]
    if not sources:
        return None
    return SyncContract(
        connector=declaration.connector,
        sync=tuple(_sync_spec(s, declaration.connector) for s in sources),
        schema_mappings=dict(declaration.schema_mappings),
        resources=declaration.resources,
    )


def contract_from_document(text: str) -> SyncContract | None:
    """The runner contract of a ``connector://resources`` body."""
    try:
        declaration = IngestSourceDeclaration.model_validate_json(text)
    except ValueError as exc:
        raise ContractError(f"connector://resources is invalid: {exc}") from exc
    return contract_from_declaration(declaration)
