"""ERPNext/Frappe vendor extractor (SDK-SOURCE-INGEST-R006.25).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.erpnext``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
turns Frappe doctypes (Employee, Customer, Sales Order, Item, Asset,
Warehouse, Issue) into typed entities and relationships.

The injected ``config.client`` is duck-typed: it only needs a
``get_list(doctype) -> list[dict]`` method returning Frappe rows. No network
or ERPNext import happens in this module; the client is supplied by the
caller.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor
from agent_connector_sdk.vendor_extractors.erpnext_helpers import (
    get_list as _get_list,
)
from agent_connector_sdk.vendor_extractors.erpnext_helpers import (
    map_assets,
    map_customers,
    map_employees,
    map_issues,
    map_items,
    map_orders,
    map_warehouses,
)

CATEGORY = "erpnext"
_DOMAIN = "erpnext"


def _get_client(config: Any) -> Any:
    """Extract the injected duck-typed client from ``config`` (attr or mapping)."""
    client = getattr(config, "client", None)
    if client is None and isinstance(config, dict):
        client = config.get("client")
    return client


def _stamp(entity: Entity) -> Entity:
    return Entity(
        id=entity.id,
        node_type=entity.node_type,
        properties={
            **entity.properties,
            "domain": entity.properties.get("domain", _DOMAIN),
            "externalToolId": entity.properties.get(
                "externalToolId", entity.id.split(":", 1)[-1]
            ),
        },
    )


def _collect(client: Any) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    org_units: dict[str, Entity] = {}
    map_employees(_get_list(client, "Employee"), entities, relationships, org_units)
    map_customers(_get_list(client, "Customer"), entities)
    map_orders(_get_list(client, "Sales Order"), entities, relationships)
    map_items(_get_list(client, "Item"), entities)
    map_assets(_get_list(client, "Asset"), entities, relationships)
    map_warehouses(_get_list(client, "Warehouse"), entities)
    map_issues(_get_list(client, "Issue"), entities, relationships)
    entities.extend(org_units.values())
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    """Build a ``ChangeSet`` from ERPNext/Frappe doctypes.

    Maps Employee/Customer/Sales Order/Item/Asset/Warehouse/Issue rows to
    typed entities and emits ``MEMBER_OF`` (Employee->OrgUnit), ``PLACED_BY``
    (SalesOrder->Customer), ``INSTANCE_OF``/``LOCATED_IN`` (Asset->Item /
    Warehouse), and ``RAISED_BY`` (Issue->Customer) relationships.
    """
    client = _get_client(config)
    if client is None:
        return ChangeSet()

    entities, relationships = _collect(client)
    # Stamp the federation key on every entity (externalToolId = Frappe doc
    # name = the entity id suffix; domain="erpnext") so write-back can resolve
    # KG entity -> ERPNext doc and reconcile across sources.
    stamped = [_stamp(entity) for entity in entities]
    return ChangeSet(entities=tuple(stamped), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="ERPNext/Frappe (HR/sales) -> KG"
)
