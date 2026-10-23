"""The typed pieces of a connector's live declaration (``connector://resources``).

A resource, its relations, the mapping of a record type onto the ontology and
one runner sync declaration.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ResourceRelation",
    "ResourceSpec",
    "SchemaMapping",
    "SyncSpec",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceRelation(_Strict):
    """One outgoing relation from a resource (an OWL object property)."""

    name: str
    label: str = ""
    target: str
    lpg_rel_type: str = ""


class SchemaMapping(_Strict):
    """How one resource's fields map onto the canonical ontology."""

    ontology_class: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class ResourceSpec(_Strict):
    """One connector resource (a record kind)."""

    name: str
    label: str = ""
    id_prefix: str = ""
    relations: list[ResourceRelation] = Field(default_factory=list)


class SyncSpec(_Strict):
    """One declared sync preset; the full preset is in ``raw``."""

    preset: str
    server: str
    tool: str
    action: str | None = None
    records_path: str | None = None
    id_field: str | None = None
    title_field: str | None = None
    text_field: str | None = None
    updated_field: str | None = None
    pagination: str | None = None
    doc_type: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
