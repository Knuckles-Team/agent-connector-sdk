"""Pure record, property and edge extraction for declared sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from scion_sdk.ingest.model import (
    Entity,
    EntityRef,
    Relationship,
)
from scion_sdk.ingest.sources import EdgeSpec, IngestSourceSpec

from ._sync_models import SourceSyncError

_SCALARS = (str, int, float, bool)


def _path(value: Any, path: str) -> Any:
    for part in [p for p in path.split(".") if p]:
        if isinstance(value, Mapping):
            value = value.get(part)
        elif (
            isinstance(value, Sequence)
            and not isinstance(value, str)
            and part.isdigit()
        ):
            index = int(part)
            value = value[index] if index < len(value) else None
        else:
            return None
    return value


def _records(result: Any, spec: IngestSourceSpec) -> list[Mapping[str, Any]]:
    found = _path(result, spec.records_path) if spec.records_path else result
    if not isinstance(found, Sequence) or isinstance(found, str | bytes):
        raise SourceSyncError(
            "malformed_result", f"{spec.records_path or 'result'} is not a record list"
        )
    records: list[Mapping[str, Any]] = []
    for item in found:
        if not isinstance(item, Mapping):
            raise SourceSyncError(
                "malformed_result", "page contains a non-object record"
            )
        identifier = item.get(spec.id_field)
        if (
            identifier is None
            or isinstance(identifier, Mapping | list)
            or not str(identifier).strip()
        ):
            raise SourceSyncError(
                "malformed_result", "record has no usable declared ID"
            )
        records.append(item)
    return records


def _properties(record: Mapping[str, Any], spec: IngestSourceSpec) -> dict[str, Any]:
    kept: dict[str, Any] = {
        key: value
        for key, value in record.items()
        if isinstance(value, _SCALARS)
        or (isinstance(value, list) and all(isinstance(v, _SCALARS) for v in value))
    }
    for name, field_name in (("title", spec.title_field), ("text", spec.text_field)):
        value = record.get(field_name) if field_name else None
        if isinstance(value, _SCALARS):
            kept.setdefault(name, value)
    return kept


def _references(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [item for item in value if item is not None and item != ""]
    return [value]


def _step_into(values: list[Any], part: str) -> list[Any]:
    items = [
        item
        for value in values
        for item in (value if isinstance(value, list) else [value])
    ]
    return [item[part] for item in items if isinstance(item, Mapping) and part in item]


def _resolve(record: Mapping[str, Any], path: str) -> list[Any]:
    """The values at dotted ``path``; a list on the way is mapped element-wise."""
    values: list[Any] = [record]
    for part in path.split("."):
        values = _step_into(values, part)
    return [ref for value in values for ref in _references(value)]


def _edges(
    record_id: str, record: Mapping[str, Any], spec: IngestSourceSpec
) -> list[tuple[Entity | None, Relationship]]:
    """The target records and relationships ``spec.edges`` declare for ``record``."""
    out: list[tuple[Entity | None, Relationship]] = []
    for edge in spec.edges:
        for ref in _resolve(record, edge.target_field):
            out.extend(_edge(record_id, spec.record_type, edge=edge, ref=ref))
    return out


def _edge(
    record_id: str, record_type: str, *, edge: EdgeSpec, ref: Any
) -> list[tuple[Entity | None, Relationship]]:
    element = ref if isinstance(ref, Mapping) else {}
    raw = element.get(edge.target_id_key) if edge.target_id_key and element else ref
    if raw is None or isinstance(raw, Mapping | list) or not str(raw).strip():
        return []
    target_id = edge.target_id_template.format(type=edge.target_type, id=raw)
    if edge.target_stream is not None:
        reference = EntityRef(id=target_id, stream=edge.target_stream)
        return [
            (
                None,
                Relationship(
                    source=EntityRef(id=record_id, node_type=record_type),
                    target=reference,
                    relationship=edge.relationship,
                ),
            )
        ]
    properties = {
        name: element.get(key)
        for name, key in edge.target_fields.items()
        if isinstance(element.get(key), _SCALARS)
    }
    target = Entity(id=target_id, node_type=edge.target_type, properties=properties)
    relationship = Relationship(
        source=EntityRef(id=record_id, node_type=record_type),
        target=target_id,
        relationship=edge.relationship,
    )
    return [(target, relationship)]
