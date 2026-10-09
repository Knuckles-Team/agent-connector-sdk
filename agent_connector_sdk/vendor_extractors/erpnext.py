"""ERPNext/Frappe vendor extractor (SDK-SOURCE-INGEST-R006.25).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.erpnext``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
turns Frappe doctypes (Employee, Customer, Sales Order, Item, Asset,
Warehouse, Issue) into typed entities and relationships.

The injected ``config.client`` is duck-typed: it only needs a
``get_list(doctype) -> list[dict]`` method returning Frappe rows. No network
or ERPNext import happens in this module; the client is supplied by the caller.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "erpnext"
_DOMAIN = "erpnext"


class _DoctypeSpec(NamedTuple):
    """A doctype with no outgoing relationships: just name + flat properties."""

    doctype: str
    id_prefix: str
    node_type: str
    name_keys: tuple[str, ...]
    prop_specs: tuple[tuple[str, tuple[str, ...]], ...]


_SIMPLE_DOCTYPES = (
    _DoctypeSpec(
        "Customer",
        "customer",
        "Customer",
        ("name", "customer", "customer_name"),
        (("customer_name", ("customer_name", "name")),),
    ),
    _DoctypeSpec(
        "Item",
        "item",
        "Item",
        ("name", "item_code", "item_name"),
        (
            ("item_name", ("item_name", "name")),
            ("item_group", ("item_group",)),
            ("stock_uom", ("stock_uom",)),
            ("actual_qty", ("actual_qty", "opening_stock")),
        ),
    ),
    _DoctypeSpec(
        "Warehouse",
        "warehouse",
        "Warehouse",
        ("name", "warehouse_name"),
        (("name", ("warehouse_name", "name")),),
    ),
)


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


def _doctype_entities(client: Any, spec: _DoctypeSpec) -> list[Entity]:
    """Build entities for a doctype that emits no outgoing relationships."""
    entities: list[Entity] = []
    for row in _get_list(client, spec.doctype):
        name = _first(row, *spec.name_keys)
        if name is None:
            continue
        props = {key: _first(row, *keys) for key, keys in spec.prop_specs}
        entities.append(
            Entity(
                id=f"{spec.id_prefix}:{name}",
                node_type=spec.node_type,
                properties=_props(**props),
            )
        )
    return entities


def _employee_items(
    client: Any,
) -> tuple[list[Entity], list[Entity], list[Relationship]]:
    """Build Employee entities, implied OrgUnit entities, and ``MEMBER_OF`` links."""
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
    return entities, list(org_units.values()), relationships


def _sales_order_items(client: Any) -> tuple[list[Entity], list[Relationship]]:
    """Build SalesOrder entities and their ``PLACED_BY`` customer links."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
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
    return entities, relationships


def _asset_items(client: Any) -> tuple[list[Entity], list[Relationship]]:
    """Build AssetInstance entities and their item/warehouse links."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
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
    return entities, relationships


def _issue_items(client: Any) -> tuple[list[Entity], list[Relationship]]:
    """Build ErpNextIssue entities and their ``RAISED_BY`` customer links."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
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

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    emp_entities, org_entities, emp_relationships = _employee_items(client)
    entities.extend(emp_entities)
    relationships.extend(emp_relationships)

    for spec in _SIMPLE_DOCTYPES:
        entities.extend(_doctype_entities(client, spec))

    for section in (_sales_order_items, _asset_items, _issue_items):
        section_entities, section_relationships = section(client)
        entities.extend(section_entities)
        relationships.extend(section_relationships)

    entities.extend(org_entities)

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
