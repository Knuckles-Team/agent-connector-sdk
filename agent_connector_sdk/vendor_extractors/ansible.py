"""Ansible Tower/AWX vendor extractor (SDK-SOURCE-INGEST-R006.2).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.ansible``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
managed hosts become ``Server`` entities instead of agent-utilities'
``GraphNode``, carrying the same Tower host id and provenance stamp. The
client is injected through ``config`` and this module performs no I/O of its
own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "ansible"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _hosts(client: Any) -> list[dict[str, Any]]:
    lister = getattr(client, "list_hosts", None)
    if not callable(lister):
        return []
    try:
        result = lister()
    except Exception:
        return []
    return [row for row in (result or []) if isinstance(row, dict)]


def _entity(host: dict[str, Any]) -> Entity | None:
    host_id = host.get("id") or host.get("name")
    name = host.get("name")
    if not (host_id and name):
        return None
    properties = {
        "name": name,
        "enabled": host.get("enabled"),
        "externalToolId": str(host_id),
        "domain": CATEGORY,
    }
    return Entity(
        id=f"ansible_host:{host_id}",
        node_type="Server",
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
        for entity in (_entity(host) for host in _hosts(client))
        if entity is not None
    )
    return ChangeSet(entities=entities)


register_vendor_extractor(
    CATEGORY, extract, description="Ansible Tower hosts (inventory) -> KG entities"
)
