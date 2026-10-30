"""The typed per-connector pack declaration: one source of truth for the pack.

Every nested value is a typed model or a reference to a declared node. A
free-form property map (for example ``sourceProperties``) is refused by
``extra="forbid"``. Turtle emission and generated views build on this model.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AccessPolicy",
    "ConnectorPackDeclaration",
    "CursorPolicy",
    "DeclaredNode",
    "FieldMapping",
    "SourceObject",
]

NodeKind = Literal["feature", "tool", "prompt", "skill"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldMapping(_Frozen):
    """One source field mapped to an ontology property IRI."""

    field: str = Field(min_length=1)
    property_iri: str = Field(min_length=1)


class CursorPolicy(_Frozen):
    """How a source is read incrementally."""

    mode: Literal["cursor", "page", "offset", "none"] = "none"
    field: str | None = None

    @model_validator(mode="after")
    def _field_matches_mode(self) -> Self:
        if self.mode == "none" and self.field is not None:
            raise ValueError("a cursor field requires a mode other than none")
        return self


class AccessPolicy(_Frozen):
    """The declared access method for a source."""

    method: Literal["mcp_tool", "a2a_skill", "http_endpoint", "ingest"]
    operation: str = Field(min_length=1)


class DeclaredNode(_Frozen):
    """A feature, tool, prompt or skill and the domain class it serves."""

    kind: NodeKind
    name: str = Field(min_length=1)
    domain_class_iri: str = Field(min_length=1)


class SourceObject(_Frozen):
    """A source object bound to an ontology class IRI."""

    name: str = Field(min_length=1)
    class_iri: str = Field(min_length=1)
    field_mappings: tuple[FieldMapping, ...] = ()
    key_fields: tuple[str, ...] = ()
    cursor: CursorPolicy = CursorPolicy()
    access: AccessPolicy | None = None
    privacy_classes: tuple[str, ...] = ()
    provenance_required: bool = False
    served_by: tuple[str, ...] = ()
    """Names of declared nodes that serve this source (typed relationships)."""

    @model_validator(mode="after")
    def _keys_are_mapped(self) -> Self:
        mapped = {m.field for m in self.field_mappings}
        missing = [k for k in self.key_fields if mapped and k not in mapped]
        if missing:
            raise ValueError(f"key fields {missing} have no field mapping")
        return self


class ConnectorPackDeclaration(_Frozen):
    """Identity, contract version, sources and declared nodes of one pack."""

    connector: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    sources: tuple[SourceObject, ...] = ()
    nodes: tuple[DeclaredNode, ...] = ()

    @model_validator(mode="after")
    def _relationships_resolve(self) -> Self:
        names = [n.name for n in self.nodes]
        if len(set(names)) != len(names):
            raise ValueError("declared node names must be unique")
        source_names = [s.name for s in self.sources]
        if len(set(source_names)) != len(source_names):
            raise ValueError("source names must be unique")
        known = set(names)
        for source in self.sources:
            unknown = [n for n in source.served_by if n not in known]
            if unknown:
                raise ValueError(
                    f"source {source.name!r} references undeclared nodes {unknown}"
                )
        return self
