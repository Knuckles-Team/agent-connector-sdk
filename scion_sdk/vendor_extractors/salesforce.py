"""Salesforce CRM vendor extractor (SCION-SOURCE-INGEST-R006.7).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.salesforce`` onto this
SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`: Account ->
``Customer``, Contact -> ``Person``, Opportunity -> ``SalesOrder``, each
carrying the Salesforce ``Id`` and a relationship back to its account, instead
of agent-utilities' ``GraphNode``/``EnrichmentEdge``. The client is injected
through ``config`` and this module performs no I/O of its own; the SOQL
queried here is a fixed literal from ``_OBJECTS`` below, never caller data.
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity, Relationship
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "salesforce"

# (SObject, node type, id prefix)
_OBJECTS = [
    ("Account", "Customer", "sfaccount"),
    ("Contact", "Person", "sfcontact"),
    ("Opportunity", "SalesOrder", "sfopp"),
]


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _records(client: Any, soql: str) -> list[dict[str, Any]]:
    query = getattr(client, "query", None)
    if not callable(query):
        return []
    try:
        result = query(soql)
    except Exception:
        return []
    if isinstance(result, dict):
        records = result.get("records")
        return records if isinstance(records, list) else []
    return list(result) if isinstance(result, list) else []


def _record_entity(label: str, prefix: str, record: dict[str, Any]) -> Entity:
    record_id = record.get("Id")
    props = {
        "name": record.get("Name"),
        "externalToolId": str(record_id),
        "domain": CATEGORY,
    }
    return Entity(
        id=f"{prefix}:{record_id}",
        node_type=label,
        properties={k: v for k, v in props.items() if v is not None},
    )


def _account_relationship(
    sobject: str, node_id: str, record: dict[str, Any]
) -> Relationship | None:
    account_id = record.get("AccountId")
    if not account_id or sobject not in ("Contact", "Opportunity"):
        return None
    return Relationship(
        source=node_id,
        target=f"sfaccount:{account_id}",
        relationship="PLACED_BY" if sobject == "Opportunity" else "BELONGS_TO",
    )


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for sobject, label, prefix in _OBJECTS:
        # sobject is one of the three literals in _OBJECTS above, never
        # caller/request data, so there is no injectable input here.
        soql = f"SELECT Id, Name, AccountId FROM {sobject} LIMIT 2000"  # nosec B608
        for record in _records(client, soql):
            if not record.get("Id"):
                continue
            entity = _record_entity(label, prefix, record)
            entities.append(entity)
            rel = _account_relationship(sobject, entity.id, record)
            if rel is not None:
                relationships.append(rel)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Salesforce CRM (accounts/contacts/opps) -> KG entities",
)
