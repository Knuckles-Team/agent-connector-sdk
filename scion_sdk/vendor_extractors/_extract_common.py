"""Shared building blocks for the small vendor extractors."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from scion_sdk.ingest import ChangeSet, Entity
from scion_sdk.vendor_extractors._records import _get, _props


def _first_dict(row: Any, *keys: str) -> Any:
    """First present, non-empty value among ``keys`` of a dict row."""
    if not isinstance(row, dict):
        return None
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _dict_rows(result: Any) -> list[dict[str, Any]]:
    """The dict items of a list result; anything else is empty."""
    if not isinstance(result, list):
        return []
    return [row for row in result if isinstance(row, dict)]


def _call_dict_rows(client: Any, name: str, *, unwrap: bool = False) -> list[Any]:
    """Call a no-argument client method and return its dict rows; ``[]`` on failure.

    With ``unwrap`` a dict result is replaced by its ``data``/``value`` entry
    (or its values) before filtering.
    """
    method = getattr(client, name, None)
    try:
        result = method() if callable(method) else None
    except Exception:
        return []
    if unwrap and isinstance(result, dict):
        result = result.get("data") or result.get("value") or list(result.values())
    return _dict_rows(result)


def _entity_of(entity_id: str, node_type: str, fields: dict[str, Any]) -> Entity:
    """An ``Entity`` whose ``None``-valued fields are dropped."""
    return Entity(id=entity_id, node_type=node_type, properties=_props(**fields))


def _present(
    rows: Iterable[Any], build: Callable[[Any], Entity | None]
) -> list[Entity]:
    """Entities built from ``rows``, skipping those ``build`` rejects."""
    return [entity for entity in map(build, rows) if entity is not None]


def _client_changeset(
    config: Any, build: Callable[[Any], Iterable[Entity]]
) -> ChangeSet:
    """An entities-only ``ChangeSet`` from the injected client, or empty."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    return ChangeSet(entities=tuple(build(client)))
