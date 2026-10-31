"""Record-to-model conversion helpers shared by every mapper."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.model import Document, Entity, Relationship

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
