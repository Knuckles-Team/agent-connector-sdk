"""Uptime Kuma vendor extractor (SDK-SOURCE-INGEST-R006.1).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.uptime_kuma``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
monitors become ``Service`` entities instead of agent-utilities' ``GraphNode``,
carrying the same Uptime Kuma id, status, and provenance stamp. The client is
injected through ``config`` and this module performs no I/O of its own; it is
tolerant of the dict- or list-shaped monitor collections the ``uptime_kuma_api``
client returns.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "uptime_kuma"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _monitors(client: Any) -> list[dict[str, Any]]:
    getter = getattr(client, "get_monitors", None)
    try:
        result = getter() if callable(getter) else None
    except Exception:
        return []
    if isinstance(result, dict):  # uptime_kuma_api returns {id: monitor}
        return [value for value in result.values() if isinstance(value, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _entity(monitor: dict[str, Any]) -> Entity | None:
    monitor_id = monitor.get("id") or monitor.get("name")
    if monitor_id is None:
        return None
    properties = {
        "name": monitor.get("name") or str(monitor_id),
        "ci_class": "monitor",
        "url": monitor.get("url"),
        "active": monitor.get("active"),
        "externalToolId": str(monitor_id),
        "domain": CATEGORY,
    }
    return Entity(
        id=f"uptime_monitor:{monitor_id}",
        node_type="Service",
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
        for entity in (_entity(monitor) for monitor in _monitors(client))
        if entity is not None
    )
    return ChangeSet(entities=entities)


register_vendor_extractor(
    CATEGORY, extract, description="Uptime Kuma monitors -> KG entities"
)
