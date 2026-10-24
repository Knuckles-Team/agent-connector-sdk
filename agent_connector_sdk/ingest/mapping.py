"""Record-to-entity mapping a connector declares and the SDK applies.

A connector keeps only what is specific to its source: which record field is
the id, which fields become properties and which fields point at other
records. It states that as a :class:`RecordMap`, or as a small function that
fills a :class:`Mapped`. Entity, relationship and document construction, field
validation and de-duplication of shared endpoints live here.

    ACCOUNT = RecordMap(
        node_type="Account",
        id_template="salesforce:Account:{Id}",
        id_keys=("Id",),
        fields={"name": "Name", "industry": "Industry"},
        external_id="Id",
        edges=(EdgeMap("ownedBy", "OwnerId", "salesforce:User:{OwnerId}", target_type="Person"),),
    )
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_connector_sdk.ingest.errors import IngestError
from agent_connector_sdk.ingest.model import Document, Entity, Relationship

__all__ = [
    "EdgeMap",
    "Mapped",
    "Mapper",
    "RecordMap",
    "document_from_record",
    "entity_from_record",
    "ext_id",
    "read_field",
    "records_of",
    "relationship_from_record",
    "slug",
]

_ENTITY_RESERVED = frozenset({"id", "node_type"})
_RELATIONSHIP_RESERVED = frozenset({"source", "target", "relationship"})
_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def read_field(
    record: Mapping[str, Any], key: str, *, required: bool = True, kind: type = str
) -> Any:
    """One validated field of ``record``.

    Raises:
        IngestError: the field is required and missing or empty, or it is not
            a ``kind``. A missing optional field reads as ``None``.
    """
    value = record.get(key)
    if value is None or value == "":
        if required:
            raise IngestError(f"record is missing required field {key!r}")
        return None
    if kind is str and isinstance(value, (int,)) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, kind):
        raise IngestError(f"record field {key!r} must be a {kind.__name__}")
    return value


def records_of(data: Any, key: str = "data") -> list[dict[str, Any]]:
    """The record list of a collection response: a bare list or ``{key: [...]}``."""
    if isinstance(data, Mapping):
        data = data.get(key)
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, Mapping)]
    return []


def ext_id(record: Mapping[str, Any], *keys: str) -> str | None:
    """The first non-empty value among ``keys``, as a string."""
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def slug(text: Any, *, default: str = "item") -> str:
    """A lower-case id-safe slug of ``text``."""
    return _SLUG_RUN.sub("-", str(text or "").lower()).strip("-") or default


def entity_from_record(record: Mapping[str, Any]) -> Entity:
    """An :class:`Entity` from ``{"id", "node_type", ...properties}``."""
    return Entity(
        id=read_field(record, "id"),
        node_type=read_field(record, "node_type"),
        properties={k: v for k, v in record.items() if k not in _ENTITY_RESERVED},
    )


def relationship_from_record(record: Mapping[str, Any]) -> Relationship:
    """A :class:`Relationship` from ``{"source", "target", "relationship", ...}``."""
    properties = {k: v for k, v in record.items() if k not in _RELATIONSHIP_RESERVED}
    return Relationship(
        source=read_field(record, "source"),
        target=read_field(record, "target"),
        relationship=read_field(record, "relationship"),
        properties=properties or None,
    )


def document_from_record(record: Mapping[str, Any]) -> Document:
    """A :class:`Document` from ``{"id", "text", "title"?, "source_uri"?, ...}``."""
    reserved = {"id", "text", "title", "source_uri", "updated_at"}
    return Document(
        id=read_field(record, "id"),
        text=read_field(record, "text"),
        title=record.get("title"),
        source_uri=record.get("source_uri"),
        properties={k: v for k, v in record.items() if k not in reserved},
        updated_at=record.get("updated_at"),
    )


@dataclass
class Mapped:
    """What a mapper produced: entities, edges and documents, de-duplicated by id."""

    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set, repr=False)

    def entity(self, id: str, node_type: str, **properties: Any) -> Mapped:
        """Add an entity (a repeated ``id`` is added once)."""
        if id not in self._seen:
            self._seen.add(id)
            self.entities.append(Entity(id, node_type, properties))
        return self

    def edge(
        self, source: str, target: str, relationship: str, **properties: Any
    ) -> Mapped:
        """Add a relationship from ``source`` to ``target``."""
        self.relationships.append(
            Relationship(source, target, relationship, properties or None)
        )
        return self

    def document(
        self,
        id: str,
        text: str,
        *,
        title: str | None = None,
        source_uri: str | None = None,
        **properties: Any,
    ) -> Mapped:
        """Add a text document."""
        self.documents.append(Document(id, text, title, source_uri, properties))
        return self

    def extend(self, other: Mapped) -> Mapped:
        """Fold ``other`` in, keeping each entity id once."""
        for entity in other.entities:
            self.entity(entity.id, entity.node_type, **entity.properties)
        self.relationships.extend(other.relationships)
        self.documents.extend(other.documents)
        return self


Mapper = Callable[[Sequence[Mapping[str, Any]]], Mapped]


@dataclass(frozen=True)
class EdgeMap:
    """A relationship from a record to the record named by one of its fields.

    ``target_template`` is formatted with the record; the edge is skipped when
    the ``target_field`` is empty. When ``target_type`` is set the target is
    also emitted once as an entity carrying ``target_fields``.
    """

    relationship: str
    target_field: str
    target_template: str
    target_type: str | None = None
    target_fields: Mapping[str, str] = field(default_factory=dict)
    properties: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecordMap:
    """Declarative record-to-entity mapping; a callable :data:`Mapper`.

    Attributes:
        node_type: The manifest resource each record becomes.
        id_template: Formatted with the record to form the entity id.
        id_keys: Fields whose first non-empty value is the source id; a record
            with none is skipped, or raises when ``strict``.
        fields: Property name to record key (a dotted key reads nested maps).
        external_id: Record key stored as ``externalToolId`` when set.
        constants: Properties added unchanged.
        edges: Relationships to other records.
        strict: Raise :class:`IngestError` for a record with no id.
    """

    node_type: str
    id_template: str
    id_keys: tuple[str, ...] = ("id",)
    fields: Mapping[str, str] = field(default_factory=dict)
    external_id: str | None = None
    constants: Mapping[str, Any] = field(default_factory=dict)
    edges: tuple[EdgeMap, ...] = ()
    strict: bool = False

    def __call__(self, records: Sequence[Mapping[str, Any]]) -> Mapped:
        mapped = Mapped()
        for record in records or ():
            self._apply(mapped, record)
        return mapped

    def _apply(self, mapped: Mapped, record: Mapping[str, Any]) -> None:
        source_id = ext_id(record, *self.id_keys)
        if source_id is None:
            if self.strict:
                raise IngestError(f"{self.node_type} record has none of {self.id_keys}")
            return
        context = {**record, "_id": source_id}
        node_id = self.id_template.format_map(context)
        properties = {name: _dig(record, key) for name, key in self.fields.items()}
        properties.update(self.constants)
        if self.external_id is not None:
            properties["externalToolId"] = str(
                _dig(record, self.external_id) or source_id
            )
        mapped.entity(node_id, self.node_type, **properties)
        for edge in self.edges:
            target = record.get(edge.target_field)
            if target is None or target == "":
                continue
            target_id = edge.target_template.format_map(
                {**context, edge.target_field: target}
            )
            if edge.target_type is not None:
                mapped.entity(
                    target_id,
                    edge.target_type,
                    **{n: _dig(record, k) for n, k in edge.target_fields.items()},
                )
            mapped.edge(node_id, target_id, edge.relationship, **edge.properties)


def _dig(record: Mapping[str, Any], key: str) -> Any:
    value: Any = record
    for part in key.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def apply_mapper(
    mapper: Mapper | Iterable[Mapper], records: Sequence[Mapping[str, Any]]
) -> Mapped:
    """Run one mapper, or several in order, over ``records``."""
    if callable(mapper):
        return mapper(records)
    out = Mapped()
    for each in mapper:
        out.extend(each(records))
    return out
