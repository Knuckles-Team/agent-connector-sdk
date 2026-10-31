"""Metadata declarations for connector read tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scion_sdk.ingest.sources import IngestSourceSpec

#: The tool ``meta`` key holding a tool's source declarations.
META_KEY = "connector_sources"
#: The generated module a package may ship to declare sources by tool name.
SOURCES_MODULE = "connector_sources"


def source_meta(
    *,
    source_id: str,
    record_type: str,
    id_field: str,
    ontology_class: str | None = None,
    fields: Mapping[str, str] | None = None,
    tool: str | None = None,
    **options: Any,
) -> dict[str, Any]:
    """The ``meta=`` argument that declares a read tool as an ingestible source.

    ``options`` are the other :class:`IngestSourceSpec` fields (records path,
    title/text/cursor fields, paging) and ``preset`` (extra runner extraction
    fields). ``ontology_class`` and ``fields`` map the record type onto the
    connector ontology. Pass ``mcp.tool(..., meta=source_meta(...))``; combine
    several with :func:`merge_meta`-style dict update on ``META_KEY`` lists.
    ``tool`` names the read tool when the declaration lives in a module that
    does not decorate the tool (``<package>.connector_sources.SOURCES``).
    """
    entry: dict[str, Any] = {
        "source_id": source_id,
        "record_type": record_type,
        "id_field": id_field,
        **options,
    }
    if ontology_class is not None or fields:
        entry["mapping"] = {
            "ontology_class": ontology_class,
            "fields": dict(fields or {}),
        }
    IngestSourceSpec.model_validate(
        {**{k: v for k, v in entry.items() if k != "mapping"}, "tools": ("x",)}
    )
    entry.setdefault("preset", {})
    if tool is not None:
        entry["tool"] = tool
    return {META_KEY: [entry]}


def _cursor_delta_preset() -> dict[str, Any]:
    """Describe the shared checkpointed cursor stream contract."""
    return {
        "params_style": "args",
        "params": {"mode": "delta"},
        "pagination": "cursor",
        "cursor_param": "cursor",
        "cursor_path": "next",
        "updated_since_param": "state",
        "checkpoint_path": "checkpoint",
    }


def _entries(tool: Any) -> list[dict[str, Any]]:
    meta = getattr(tool, "meta", None) or {}
    value = meta.get(META_KEY) if isinstance(meta, dict) else None
    return [e for e in value or () if isinstance(e, dict)]
