"""The typed pieces of a connector's live declaration (``connector://resources``).

A resource, its relations, the mapping of a record type onto the ontology and
one runner sync declaration.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    datatypes: dict[str, str] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def _datatype_targets_are_declared(self) -> Self:
        supported = {
            "xsd:string",
            "xsd:date",
            "xsd:dateTime",
            "xsd:anyURI",
            "xsd:boolean",
            "xsd:integer",
            "xsd:int",
            "xsd:long",
            "xsd:nonNegativeInteger",
            "xsd:decimal",
            "xsd:double",
            "xsd:float",
        }
        for field, datatype in self.datatypes.items():
            target = self.fields.get(field)
            if datatype not in supported or not target or target.startswith("xsd:"):
                raise ValueError(
                    "datatype requires a supported type and explicit target"
                )
        return self


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
    feed_kind: str | None = None
