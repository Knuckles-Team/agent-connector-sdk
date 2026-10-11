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
from agent_connector_sdk.vendor_extractors import _records as rec
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "technitium_dns"


def _dicts(values: list[Any]) -> list[dict[str, Any]]:
    return [row for row in values if isinstance(row, dict)]


def _rows(result: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return _dicts(result)
    if not isinstance(result, dict):
        return []
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return _dicts(value)
    return []


def _zone_entity(zone: str, zone_id: str) -> Entity:
    return Entity(
        id=zone_id,
        node_type="ConfigurationItem",
        properties={
            "name": zone,
            "ci_class": "dns_zone",
            "externalToolId": zone,
            "domain": CATEGORY,
        },
    )


def _record_entity(zone: str, record: dict[str, Any]) -> Entity:
    record_name = record.get("name") or zone
    record_type = record.get("type") or "A"
    record_id = f"dnsrecord:{zone}:{record_name}:{record_type}"
    r_data = record.get("rData")
    value = r_data.get("value") if isinstance(r_data, dict) else record.get("value")
    candidates = {
        "name": record_name,
        "ci_class": f"dns_{record_type.lower()}",
        "record_type": record_type,
        "value": value,
        "externalToolId": record_id.split(":", 1)[1],
        "domain": CATEGORY,
    }
    return Entity(
        id=record_id,
        node_type="ConfigurationItem",
        properties={k: v for k, v in candidates.items() if v is not None},
    )


def _zone_records(
    client: Any, zone: str, zone_id: str
) -> tuple[list[Entity], list[Relationship]]:
    rows = _rows(
        rec._safe_call(client, "get_records", zone), "records", "value", "data"
    )
    entities = [_record_entity(zone, record) for record in rows]
    relationships = [
        Relationship(source=zone_id, target=entity.id, relationship="CONTAINS")
        for entity in entities
    ]
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    client = rec._get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for zone_row in _rows(
        rec._safe_call(client, "list_zones"), "zones", "value", "data"
    ):
        zone = zone_row.get("name") or zone_row.get("zone")
        if not zone:
            continue
        zone_id = f"dnszone:{zone}"
        entities.append(_zone_entity(zone, zone_id))
        rec_entities, rec_rels = _zone_records(client, zone, zone_id)
        entities.extend(rec_entities)
        relationships.extend(rec_rels)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="Technitium DNS zones/records -> KG entities"
)
