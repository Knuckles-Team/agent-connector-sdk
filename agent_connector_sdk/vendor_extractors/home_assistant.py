"""Home Assistant vendor extractor (SDK-SOURCE-INGEST-R006.4).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.home_assistant`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
entity states become ``ConfigurationItem`` entities instead of
agent-utilities' ``GraphNode``. The client is injected through ``config`` and
this module performs no I/O of its own; it is tolerant of dict- or
object-shaped states.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "homeassistant"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _attr(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and obj.get(name) not in (None, ""):
            return obj[name]
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return None


def _states(client: Any) -> list[Any]:
    getter = getattr(client, "get_states", None)
    if not callable(getter):
        return []
    try:
        return list(getter() or [])
    except Exception:
        return []


def _entity(state: Any) -> Entity | None:
    entity_id = _attr(state, "entity_id")
    if not entity_id:
        return None
    attrs = _attr(state, "attributes") or {}
    name = (
        attrs.get("friendly_name") if isinstance(attrs, dict) else None
    ) or entity_id
    properties = {
        "name": name,
        "state": _attr(state, "state"),
        "ci_class": str(entity_id).split(".", 1)[0],
        "externalToolId": str(entity_id),
        "domain": CATEGORY,
    }
    return Entity(
        id=f"ha:{entity_id}",
        node_type="ConfigurationItem",
        properties={
            key: value for key, value in properties.items() if value is not None
        },
    )


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    entities = tuple(
        entity
        for entity in (_entity(state) for state in _states(client))
        if entity is not None
    )
    return ChangeSet(entities=entities)


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Home Assistant entities (device inventory) -> KG entities",
)
