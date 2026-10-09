"""Technitium DNS vendor extractor (SDK-SOURCE-INGEST-R006.10).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.technitium_dns`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
zones and records become ``ConfigurationItem`` entities instead of
agent-utilities' ``GraphNode``, with a ``CONTAINS`` relationship from zone to
record. The client is injected through ``config`` and this module performs no
I/O of its own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "technitium_dns"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _call(client: Any, name: str, *args: Any) -> Any:
    method = getattr(client, name, None)
    if not callable(method):
        return None
    try:
        return method(*args)
    except Exception:
        return None


def _rows(result: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        for key in keys:
            value = result.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return []
    return (
        [row for row in result if isinstance(row, dict)]
        if isinstance(result, list)
        else []
    )


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for zone_row in _rows(_call(client, "list_zones"), "zones", "value", "data"):
        zone = zone_row.get("name") or zone_row.get("zone")
        if not zone:
            continue
        zone_id = f"dnszone:{zone}"
        entities.append(
            Entity(
                id=zone_id,
                node_type="ConfigurationItem",
                properties={
                    "name": zone,
                    "ci_class": "dns_zone",
                    "externalToolId": zone,
                    "domain": CATEGORY,
                },
            )
        )
        records = _rows(_call(client, "get_records", zone), "records", "value", "data")
        for record in records:
            record_name = record.get("name") or zone
            record_type = record.get("type") or "A"
            record_id = f"dnsrecord:{zone}:{record_name}:{record_type}"
            r_data = record.get("rData")
            entities.append(
                Entity(
                    id=record_id,
                    node_type="ConfigurationItem",
                    properties={
                        key: value
                        for key, value in {
                            "name": record_name,
                            "ci_class": f"dns_{record_type.lower()}",
                            "record_type": record_type,
                            "value": r_data.get("value")
                            if isinstance(r_data, dict)
                            else record.get("value"),
                            "externalToolId": record_id.split(":", 1)[1],
                            "domain": CATEGORY,
                        }.items()
                        if value is not None
                    },
                )
            )
            relationships.append(
                Relationship(source=zone_id, target=record_id, relationship="CONTAINS")
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="Technitium DNS zones/records -> KG entities"
)
