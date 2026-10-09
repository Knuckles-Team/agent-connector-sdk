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

CATEGORY = "erpnext"
_DOMAIN = "erpnext"


def _first(row: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _get_client(config: Any) -> Any:
    """Extract the injected duck-typed client from ``config`` (attr or mapping)."""
    client = getattr(config, "client", None)
    if client is None and isinstance(config, dict):
        client = config.get("client")
    return client


def _get_list(client: Any, doctype: str) -> list[dict[str, Any]]:
    """Tolerantly fetch a doctype list; never raise for an absent doctype."""
    try:
        rows = client.get_list(doctype)
    except Exception:
        return []
    return list(rows or [])


def _props(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


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

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    org_units: dict[str, Entity] = {}

    for row in _get_list(client, "Employee"):
        name = _first(row, "name", "employee", "employee_name")
        if name is None:
            continue
        department = _first(row, "department", "dept")
        node_id = f"employee:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="Employee",
                properties=_props(
                    employee_name=_first(row, "employee_name", "name"),
                    department=department,
                ),
            )
        )
        if department is not None:
            org_id = f"orgunit:{department}"
            if org_id not in org_units:
                org_units[org_id] = Entity(
                    id=org_id, node_type="OrgUnit", properties={"name": department}
                )
            relationships.append(
                Relationship(source=node_id, target=org_id, relationship="MEMBER_OF")
            )

    for row in _get_list(client, "Customer"):
        name = _first(row, "name", "customer", "customer_name")
        if name is None:
            continue
        entities.append(
            Entity(
                id=f"customer:{name}",
                node_type="Customer",
                properties=_props(customer_name=_first(row, "customer_name", "name")),
            )
        )

    for row in _get_list(client, "Sales Order"):
        name = _first(row, "name", "order")
        if name is None:
            continue
        node_id = f"order:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="SalesOrder",
                properties=_props(grand_total=_first(row, "grand_total", "total")),
            )
        )
        customer = _first(row, "customer", "customer_name")
        if customer is not None:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"customer:{customer}",
                    relationship="PLACED_BY",
                )
            )

    for row in _get_list(client, "Item"):
        name = _first(row, "name", "item_code", "item_name")
        if name is None:
            continue
        entities.append(
            Entity(
                id=f"item:{name}",
                node_type="Item",
                properties=_props(
                    item_name=_first(row, "item_name", "name"),
                    item_group=_first(row, "item_group"),
                    stock_uom=_first(row, "stock_uom"),
                    actual_qty=_first(row, "actual_qty", "opening_stock"),
                ),
            )
        )

    for row in _get_list(client, "Asset"):
        name = _first(row, "name", "asset_name")
        if name is None:
            continue
        node_id = f"asset:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="AssetInstance",
                properties=_props(
                    name=_first(row, "asset_name", "name"),
                    asset_category=_first(row, "asset_category"),
                    lifecycleStage=_first(row, "status"),
                    endOfLifeDate=_first(
                        row, "disposal_date", "expected_value_after_useful_life"
                    ),
                ),
            )
        )
        item = _first(row, "item_code", "item")
        if item is not None:
            relationships.append(
                Relationship(
                    source=node_id, target=f"item:{item}", relationship="INSTANCE_OF"
                )
            )
        warehouse = _first(row, "warehouse", "location")
        if warehouse is not None:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"warehouse:{warehouse}",
                    relationship="LOCATED_IN",
                )
            )

    for row in _get_list(client, "Warehouse"):
        name = _first(row, "name", "warehouse_name")
        if name is None:
            continue
        entities.append(
            Entity(
                id=f"warehouse:{name}",
                node_type="Warehouse",
                properties=_props(name=_first(row, "warehouse_name", "name")),
            )
        )

    for row in _get_list(client, "Issue"):
        name = _first(row, "name", "subject")
        if name is None:
            continue
        node_id = f"erpnextissue:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="ErpNextIssue",
                properties=_props(
                    subject=_first(row, "subject", "name"),
                    status=_first(row, "status", "state"),
                    priority=_first(row, "priority"),
                ),
            )
        )
        customer = _first(row, "customer", "customer_name")
        if customer is not None:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"customer:{customer}",
                    relationship="RAISED_BY",
                )
            )

    entities.extend(org_units.values())
    # Stamp the federation key on every entity (externalToolId = Frappe doc
    # name = the entity id suffix; domain="erpnext") so write-back can resolve
    # KG entity -> ERPNext doc and reconcile across sources.
    stamped = [
        Entity(
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
        for entity in entities
    ]
    return ChangeSet(entities=tuple(stamped), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="ERPNext/Frappe (HR/sales) -> KG"
)
