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

from agent_connector_sdk.ingest.for_each import ForEach, check_for_each
from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping

__all__ = ["EdgeSpec", "IngestSourceDeclaration", "IngestSourceSpec"]

_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EdgeSpec(_Strict):
    """A relationship from each record to the record one of its fields names.

    The declarative form of :class:`~agent_connector_sdk.ingest.mapping.EdgeMap`
    for declared sources (SDK-SOURCE-INGEST-R004.36). ``target_field`` is a
    dotted path into the record; it may resolve to a scalar id, a mapping (a
    reference such as ServiceNow's ``{"value": sys_id}``) or a list of either.
    For a mapping, ``target_id_key`` names the key that holds the id.
    ``target_id_template`` forms the target record id from ``{type}`` and
    ``{id}``. The target is emitted once per batch as a ``target_type`` record
    carrying ``target_fields`` (property to key of the referenced mapping), and
    the edge type is ``relationship``: the pack ontology must declare it as an
    object property whose domain is the source record type. With
    ``target_stream`` the target is that source's own record (for example a CI
    of ``cmdb-cis``): no stub is emitted and the edge names that stream.
    """

    relationship: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    target_field: str = Field(min_length=1)
    target_type: str = Field(min_length=1, max_length=128)
    target_id_key: str | None = None
    target_id_template: str = "{type}:{id}"
    target_fields: dict[str, str] = Field(default_factory=dict)
    target_stream: str | None = Field(default=None, pattern=_ID_PATTERN)

    @model_validator(mode="after")
    def _check(self) -> EdgeSpec:
        if "{id}" not in self.target_id_template:
            raise ValueError("target_id_template must contain {id}")
        return self


class IngestSourceSpec(_Strict):
    """One ingestible source: the tools that page it and how its records read.

    ``tools`` are called in order; each must be a read-only tool. ``arguments``
    are the fixed arguments of every call. A ``page`` source adds
    ``page_param`` (starting at ``start_page``) and ``page_size_param``; a
    page shorter than ``page_size`` ends the sweep. ``cursor_field`` names the
    record field that orders records; an ``incremental`` source skips records
    at or before the stored cursor. ``for_each`` runs the source once per
    record of a parent source, passing the parent's field as a tool argument.
    ``edges`` link each record to the records its reference fields name.
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
    for_each: ForEach | None = None
    edges: tuple[EdgeSpec, ...] = ()

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
        check_for_each({s.source_id: s.for_each for s in self.sources})
        return self

    def source(self, source_id: str) -> IngestSourceSpec | None:
        """The declared source ``source_id``, or ``None``."""
        return next((s for s in self.sources if s.source_id == source_id), None)
