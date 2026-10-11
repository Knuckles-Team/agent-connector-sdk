"""Twenty CRM vendor extractor (SDK-SOURCE-INGEST-R006.19).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.twenty``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
companies become ``Customer`` entities, people become ``Person`` entities
(``BELONGS_TO`` their company), and opportunities become ``SalesOrder``
entities (``PLACED_BY`` their company) -- consistent with the Salesforce
mapping. The client is injected through ``config``; tolerant of the REST
``{"data": [...]}`` and GraphQL ``{"data": {<plural>: {"edges": [...]}}}``
list shapes. This module performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor
from agent_connector_sdk.vendor_extractors.twenty_helpers import (
    _company_ref,
    _name,
    _opportunity_entity,
    _person_entity,
    _props,
    _records,
)

CATEGORY = "twenty"
_DOMAIN = "twenty"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _call(client: Any, name: str) -> Any:
    method = getattr(client, name, None)
    try:
        return method() if callable(method) else None
    except Exception:
        return None


def _company_entities(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for company in _records(_call(client, "get_companies"), "companies"):
        company_id = company.get("id")
        if company_id:
            entities.append(
                Entity(
                    id=f"twcompany:{company_id}",
                    node_type="Customer",
                    properties=_props(
                        name=_name(company, "name"),
                        externalToolId=str(company_id),
                        domain=_DOMAIN,
                    ),
                )
            )
    return entities


def _linked(
    client: Any,
    *,
    method: str,
    plural: str,
    prefix: str,
    build: Any,
    relationship: str,
) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for record in _records(_call(client, method), plural):
        record_id = record.get("id")
        if not record_id:
            continue
        node_id = f"{prefix}:{record_id}"
        entities.append(build(record, node_id, record_id))
        company_ref = _company_ref(record)
        if company_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"twcompany:{company_ref}",
                    relationship=relationship,
                )
            )
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities = _company_entities(client)
    people, person_rels = _linked(
        client,
        method="get_people",
        plural="people",
        prefix="twperson",
        build=_person_entity,
        relationship="BELONGS_TO",
    )
    opps, opp_rels = _linked(
        client,
        method="get_opportunities",
        plural="opportunities",
        prefix="twopp",
        build=_opportunity_entity,
        relationship="PLACED_BY",
    )
    return ChangeSet(
        entities=tuple(entities + people + opps),
        relationships=tuple(person_rels + opp_rels),
    )


register_vendor_extractor(
    CATEGORY, extract, description="Twenty CRM (companies/people/opps) -> KG"
)
