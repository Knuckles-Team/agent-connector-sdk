"""Odoo CRM vendor extractor (SDK-SOURCE-INGEST-R006.15).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.odoo``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`::

    res.partner -> ``Customer`` id=odoo_customer:{id}
    crm.lead    -> ``Lead``     id=odoo_lead:{id}   (BELONGS_TO customer)

So Odoo joins the same ``crm`` cohort as Twenty, instead of agent-utilities'
``GraphNode``/``EnrichmentEdge``. The client is injected through ``config``
(expected to expose ``list_partners()``/``list_leads()``) and this module
performs no I/O of its own; all field access is tolerant.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "odoo"


def _get(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _first(record: Any, *keys: str) -> Any:
    for key in keys:
        value = _get(record, key)
        if value is not None and value != "":
            return value
    return None


def _call(client: Any, name: str) -> list[Any]:
    method = getattr(client, name, None)
    if not callable(method):
        return []
    try:
        result = method()
    except TypeError:
        try:
            result = method({})
        except Exception:
            return []
    except Exception:
        return []
    if isinstance(result, dict):
        result = (
            result.get("records") or result.get("items") or result.get("data") or []
        )
    return list(result) if result else []


def _rel_id(value: Any) -> Any:
    """Odoo many2one fields are ``[id, label]`` pairs -- return the id."""
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    for record in _call(client, "list_partners"):
        partner_id = _first(record, "id", "name")
        if not partner_id:
            continue
        entities.append(
            Entity(
                id=f"odoo_customer:{partner_id}",
                node_type="Customer",
                properties={
                    "name": _first(record, "display_name", "name"),
                    "capability": "crm",
                },
            )
        )

    for record in _call(client, "list_leads"):
        lead_id = _first(record, "id", "name")
        if not lead_id:
            continue
        node_id = f"odoo_lead:{lead_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type="Lead",
                properties={
                    "name": _first(record, "display_name", "name"),
                    "capability": "crm",
                },
            )
        )
        partner_ref = _rel_id(_first(record, "partner_id", "partner"))
        if partner_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"odoo_customer:{partner_ref}",
                    relationship="BELONGS_TO",
                )
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="Odoo CRM (customers/leads) -> KG entities"
)
