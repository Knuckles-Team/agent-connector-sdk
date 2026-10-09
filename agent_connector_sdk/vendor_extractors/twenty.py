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


def _records_from_connection(conn: Any) -> list[dict[str, Any]] | None:
    """A GraphQL ``{edges:[{node:...}]}`` or plain-list connection, if shaped so."""
    if isinstance(conn, dict) and isinstance(conn.get("edges"), list):
        return [
            edge["node"]
            for edge in conn["edges"]
            if isinstance(edge, dict) and edge.get("node")
        ]
    if isinstance(conn, list):
        return [row for row in conn if isinstance(row, dict)]
    return None


def _records_from_data(data: Any, plural: str) -> list[dict[str, Any]]:
    if isinstance(data, dict) and plural in data:
        resolved = _records_from_connection(data[plural])
        if resolved is not None:
            return resolved
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _records(res: Any, plural: str) -> list[dict[str, Any]]:
    """Pull records from REST ``{data:[...]}`` or GraphQL connection shapes."""
    if not isinstance(res, dict):
        return (
            [row for row in res if isinstance(row, dict)]
            if isinstance(res, list)
            else []
        )
    return _records_from_data(res.get("data", res), plural)


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


def _record_built(
    record: dict[str, Any],
    *,
    prefix: str,
    node_type: str,
    properties_fn: Any,
    relationship_kind: str | None,
) -> tuple[Entity, Relationship | None] | None:
    """A ``Customer``/``Person``/``SalesOrder`` entity -- all three share the
    same id/properties/optional-company-relationship shape, differing only in
    prefix, label, which fields become display properties, and whether (and
    as what kind) they relate back to their company."""
    record_id = record.get("id")
    if not record_id:
        return None
    node_id = f"{prefix}:{record_id}"
    entity = Entity(
        id=node_id,
        node_type=node_type,
        properties=_props(
            **properties_fn(record), externalToolId=str(record_id), domain=_DOMAIN
        ),
    )
    relationship = None
    if relationship_kind:
        company_ref = record.get("companyId") or (record.get("company") or {}).get("id")
        if company_ref:
            relationship = Relationship(
                source=node_id,
                target=f"twcompany:{company_ref}",
                relationship=relationship_kind,
            )
    return entity, relationship


def _opportunity_properties(opportunity: dict[str, Any]) -> dict[str, Any]:
    amount = opportunity.get("amount")
    return {
        "name": _name(opportunity, "name"),
        "stage": opportunity.get("stage"),
        "amount": amount.get("amountMicros") if isinstance(amount, dict) else amount,
    }


_GROUPS = (
    (
        "get_companies",
        "companies",
        "twcompany",
        "Customer",
        lambda r: {"name": _name(r, "name")},
        None,
    ),
    (
        "get_people",
        "people",
        "twperson",
        "Person",
        lambda r: {"name": _name(r, "name", "displayName"), "email": _name(r, "email")},
        "BELONGS_TO",
    ),
    (
        "get_opportunities",
        "opportunities",
        "twopp",
        "SalesOrder",
        _opportunity_properties,
        "PLACED_BY",
    ),
)


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for method, plural, prefix, node_type, properties_fn, relationship_kind in _GROUPS:
        for record in _records(_call(client, method), plural):
            built = _record_built(
                record,
                prefix=prefix,
                node_type=node_type,
                properties_fn=properties_fn,
                relationship_kind=relationship_kind,
            )
            if built is None:
                continue
            entity, relationship = built
            entities.append(entity)
            if relationship is not None:
                relationships.append(relationship)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="Twenty CRM (companies/people/opps) -> KG"
)
