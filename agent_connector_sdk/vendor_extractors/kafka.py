"""Kafka vendor extractor (SDK-SOURCE-INGEST-R006.6).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.kafka``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
topics and consumer groups become ``Topic``/``Service`` entities instead of
agent-utilities' ``GraphNode``. The client is injected through ``config`` and
this module performs no I/O of its own; it is tolerant of native/REST list
shapes.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "kafka"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _unwrap_list(result: Any) -> Any:
    """Unwrap a dict envelope (``{"topics": [...]}`` etc) to its inner list."""
    if not isinstance(result, dict):
        return result
    for key in ("topics", "data", "value", "groups"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return result


def _row_name(row: Any) -> str | None:
    """Pull a name out of a native (string) or REST (dict) list row."""
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return None
    name = row.get("name") or row.get("topic") or row.get("group_id") or row.get("groupId")
    return str(name) if name else None


def _names(result: Any) -> list[str]:
    result = _unwrap_list(result)
    if not isinstance(result, list):
        return []
    return [name for row in result if (name := _row_name(row)) is not None]


def _call(client: Any, name: str) -> Any:
    method = getattr(client, name, None)
    try:
        return method() if callable(method) else None
    except Exception:
        return None


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    for topic in _names(_call(client, "list_topics")):
        entities.append(
            Entity(
                id=f"kafka_topic:{topic}",
                node_type="Topic",
                properties={
                    "name": topic,
                    "externalToolId": topic,
                    "domain": CATEGORY,
                },
            )
        )
    for group in _names(_call(client, "list_consumer_groups")):
        entities.append(
            Entity(
                id=f"kafka_group:{group}",
                node_type="Service",
                properties={
                    "name": group,
                    "ci_class": "consumer_group",
                    "externalToolId": group,
                    "domain": CATEGORY,
                },
            )
        )
    return ChangeSet(entities=tuple(entities))


register_vendor_extractor(
    CATEGORY, extract, description="Kafka topics/consumer-groups -> KG entities"
)
