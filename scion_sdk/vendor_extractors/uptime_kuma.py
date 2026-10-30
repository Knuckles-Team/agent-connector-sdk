"""Uptime Kuma vendor extractor (SCION-SOURCE-INGEST-R006.1).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.uptime_kuma``
onto this SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`:
monitors become ``Service`` entities instead of agent-utilities' ``GraphNode``,
carrying the same Uptime Kuma id, status, and provenance stamp. The client is
injected through ``config`` and this module performs no I/O of its own; it is
tolerant of the dict- or list-shaped monitor collections the ``uptime_kuma_api``
client returns.
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity
from scion_sdk.vendor_extractors._extract_common import (
    _client_changeset,
    _entity_of,
    _present,
)
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "uptime_kuma"


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
    return _entity_of(f"uptime_monitor:{monitor_id}", "Service", properties)


def extract(config: Any) -> ChangeSet:
    return _client_changeset(
        config, lambda client: _present(_monitors(client), _entity)
    )


register_vendor_extractor(
    CATEGORY, extract, description="Uptime Kuma monitors -> KG entities"
)
