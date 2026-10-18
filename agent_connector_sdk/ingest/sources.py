"""Declared ingestible sources of a connector (SDK-SOURCE-INGEST-R004.19, R004.21).

A connector ships ``<package>/ontology/ingest_sources.json``: one entry per
source it can ingest, naming the read-only tool(s) that page through it, where
the records are in each result, the record identity and the cursor field. The
file is data, not code. :func:`register_ingest_sources_tool` serves it as the
read-only ``<prefix>_ingest_sources`` tool, so a host lists a connector's
sources through the same admitted tool path it calls the connector through.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = [
    "DECLARATION_FILE",
    "IngestSourceDeclaration",
    "IngestSourceSpec",
    "ingest_sources_tool_name",
    "load_ingest_sources",
    "register_ingest_sources_tool",
]

#: The declaration file, relative to the connector package root.
DECLARATION_FILE = Path("ontology") / "ingest_sources.json"

_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IngestSourceSpec(_Strict):
    """One ingestible source: the tools that page it and how its records read.

    ``tools`` are called in order; each must be a read-only tool. ``arguments``
    are the fixed arguments of every call. A ``page`` source adds
    ``page_param`` (starting at ``start_page``) and ``page_size_param``; a
    page shorter than ``page_size`` ends the sweep. ``cursor_field`` names the
    record field that orders records; an ``incremental`` source skips records
    at or before the stored cursor.
    """

    source_id: str = Field(pattern=_ID_PATTERN)
    record_type: str = Field(min_length=1, max_length=128)
    tools: tuple[str, ...] = Field(min_length=1)
    records_path: str = ""
    id_field: str = Field(min_length=1)
    title_field: str | None = None
    text_field: str | None = None
    cursor_field: str | None = None
    incremental: bool = False
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    pagination: Literal["none", "page"] = "none"
    page_param: str | None = None
    page_size_param: str | None = None
    page_size: int = Field(default=100, ge=1, le=1000)
    start_page: int = Field(default=1, ge=0)
    description: str = ""

    @model_validator(mode="after")
    def _check(self) -> IngestSourceSpec:
        if self.incremental and not self.cursor_field:
            raise ValueError(
                f"incremental source {self.source_id!r} needs a cursor_field"
            )
        if self.pagination == "page" and not self.page_param:
            raise ValueError(f"paged source {self.source_id!r} needs a page_param")
        if len(set(self.tools)) != len(self.tools) or not all(self.tools):
            raise ValueError(f"source {self.source_id!r} tools must be unique names")
        return self


class IngestSourceDeclaration(_Strict):
    """Every ingestible source one connector declares."""

    connector: str = Field(min_length=1, max_length=128)
    sources: tuple[IngestSourceSpec, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> IngestSourceDeclaration:
        ids = [source.source_id for source in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("source_id values must be unique within a connector")
        return self

    def source(self, source_id: str) -> IngestSourceSpec | None:
        """The declared source ``source_id``, or ``None``."""
        return next((s for s in self.sources if s.source_id == source_id), None)


def load_ingest_sources(package_root: Path) -> IngestSourceDeclaration | None:
    """The package's declaration, or ``None`` when it declares no source.

    Raises:
        ValueError: the declaration file exists but is not a valid declaration.
    """
    path = Path(package_root) / DECLARATION_FILE
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{DECLARATION_FILE} is not readable JSON") from exc
    return IngestSourceDeclaration.model_validate(document)


def ingest_sources_tool_name(prefix: str) -> str:
    """The served declaration tool name for an operation-tool ``prefix``."""
    return f"{prefix}_ingest_sources"


def register_ingest_sources_tool(
    mcp: Any, prefix: str, declaration: IngestSourceDeclaration
) -> str:
    """Serve ``declaration`` as the read-only ``<prefix>_ingest_sources`` tool."""
    from mcp.types import ToolAnnotations

    name = ingest_sources_tool_name(prefix)
    payload: Mapping[str, Any] = declaration.model_dump(mode="json")

    def ingest_sources() -> dict[str, Any]:
        """List the sources this connector can ingest and the tools that page them."""
        return dict(payload)

    mcp.tool(
        ingest_sources,
        name=name,
        tags={"ingest"},
        annotations=ToolAnnotations(
            title="Ingestible sources",
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    return name
