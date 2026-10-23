"""Declared ingestible sources of a connector (SDK-SOURCE-INGEST-R004.19, R004.21).

A connector declares one source per ingestible record type with
``source_meta`` on the read tool that pages it (SDK-CONNECTOR-CONTROL-R075.2).
A source names the read-only tool, where the records are in each result, the
record identity and the cursor field. The server serves the assembled
declaration as the resource ``connector://resources``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping

__all__ = ["IngestSourceDeclaration", "IngestSourceSpec"]

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
    server: str = ""
    preset: dict[str, JsonValue] | None = None

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
    schema_mappings: dict[str, SchemaMapping] = Field(default_factory=dict)
    resources: tuple[ResourceSpec, ...] = ()
    descriptors: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> IngestSourceDeclaration:
        ids = [source.source_id for source in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("source_id values must be unique within a connector")
        return self

    def source(self, source_id: str) -> IngestSourceSpec | None:
        """The declared source ``source_id``, or ``None``."""
        return next((s for s in self.sources if s.source_id == source_id), None)
