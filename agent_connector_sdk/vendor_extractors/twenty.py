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

CATEGORY = "twenty"
_DOMAIN = "twenty"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _records(res: Any, plural: str) -> list[dict[str, Any]]:
    """Pull records from REST ``{data:[...]}`` or GraphQL connection shapes."""
    if not isinstance(res, dict):
        return (
            [row for row in res if isinstance(row, dict)]
            if isinstance(res, list)
            else []
        )
    data = res.get("data", res)
    if isinstance(data, dict) and plural in data:
        conn = data[plural]
        if isinstance(conn, dict) and isinstance(conn.get("edges"), list):
            return [
                edge["node"]
                for edge in conn["edges"]
                if isinstance(edge, dict) and edge.get("node")
            ]
        if isinstance(conn, list):
            return [row for row in conn if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _call(client: Any, name: str) -> Any:
    method = getattr(client, name, None)
    try:
        return method() if callable(method) else None
    except Exception:
        return None


def _name(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):  # Twenty FullName {firstName,lastName}
            joined = " ".join(str(part) for part in value.values() if part)
            if joined.strip():
                return joined.strip()
        elif value:
            return str(value)
    return None


def _props(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

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

    for person in _records(_call(client, "get_people"), "people"):
        person_id = person.get("id")
        if not person_id:
            continue
        node_id = f"twperson:{person_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type="Person",
                properties=_props(
                    name=_name(person, "name", "displayName"),
                    email=_name(person, "email"),
                    externalToolId=str(person_id),
                    domain=_DOMAIN,
                ),
            )
        )
        company_ref = person.get("companyId") or (person.get("company") or {}).get("id")
        if company_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"twcompany:{company_ref}",
                    relationship="BELONGS_TO",
                )
            )

    for opportunity in _records(_call(client, "get_opportunities"), "opportunities"):
        opp_id = opportunity.get("id")
        if not opp_id:
            continue
        node_id = f"twopp:{opp_id}"
        amount = opportunity.get("amount")
        entities.append(
            Entity(
                id=node_id,
                node_type="SalesOrder",
                properties=_props(
                    name=_name(opportunity, "name"),
                    stage=opportunity.get("stage"),
                    amount=amount.get("amountMicros")
                    if isinstance(amount, dict)
                    else amount,
                    externalToolId=str(opp_id),
                    domain=_DOMAIN,
                ),
            )
        )
        company_ref = opportunity.get("companyId") or (
            opportunity.get("company") or {}
        ).get("id")
        if company_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"twcompany:{company_ref}",
                    relationship="PLACED_BY",
                )
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="Twenty CRM (companies/people/opps) -> KG"
)
