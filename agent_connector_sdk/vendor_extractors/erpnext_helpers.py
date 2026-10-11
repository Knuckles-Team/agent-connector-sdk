"""Per-doctype row mappers for the ERPNext extractor (see ``erpnext.py``)."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import Entity, Relationship


def first(row: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def get_list(client: Any, doctype: str) -> list[dict[str, Any]]:
    """Tolerantly fetch a doctype list; never raise for an absent doctype."""
    try:
        rows = client.get_list(doctype)
    except Exception:
        return []
    return list(rows or [])


def props(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _link(
    rels: list[Relationship], *, source: str, prefix: str, value: Any, kind: str
) -> None:
    if value is not None:
        rels.append(
            Relationship(source=source, target=f"{prefix}:{value}", relationship=kind)
        )


def map_employees(
    rows: list[dict[str, Any]],
    entities: list[Entity],
    rels: list[Relationship],
    *,
    org_units: dict[str, Entity],
) -> None:
    for row in rows:
        name = first(row, "name", "employee", "employee_name")
        if name is None:
            continue
        department = first(row, "department", "dept")
        node_id = f"employee:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="Employee",
                properties=props(
                    employee_name=first(row, "employee_name", "name"),
                    department=department,
                ),
            )
        )
        if department is None:
            continue
        org_id = f"orgunit:{department}"
        if org_id not in org_units:
            org_units[org_id] = Entity(
                id=org_id, node_type="OrgUnit", properties={"name": department}
            )
        rels.append(
            Relationship(source=node_id, target=org_id, relationship="MEMBER_OF")
        )


def map_customers(rows: list[dict[str, Any]], entities: list[Entity]) -> None:
    for row in rows:
        name = first(row, "name", "customer", "customer_name")
        if name is None:
            continue
        entities.append(
            Entity(
                id=f"customer:{name}",
                node_type="Customer",
                properties=props(customer_name=first(row, "customer_name", "name")),
            )
        )


def map_orders(
    rows: list[dict[str, Any]], entities: list[Entity], rels: list[Relationship]
) -> None:
    for row in rows:
        name = first(row, "name", "order")
        if name is None:
            continue
        node_id = f"order:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="SalesOrder",
                properties=props(grand_total=first(row, "grand_total", "total")),
            )
        )
        _link(
            rels,
            source=node_id,
            prefix="customer",
            value=first(row, "customer", "customer_name"),
            kind="PLACED_BY",
        )


def map_items(rows: list[dict[str, Any]], entities: list[Entity]) -> None:
    for row in rows:
        name = first(row, "name", "item_code", "item_name")
        if name is None:
            continue
        entities.append(
            Entity(
                id=f"item:{name}",
                node_type="Item",
                properties=props(
                    item_name=first(row, "item_name", "name"),
                    item_group=first(row, "item_group"),
                    stock_uom=first(row, "stock_uom"),
                    actual_qty=first(row, "actual_qty", "opening_stock"),
                ),
            )
        )


def map_assets(
    rows: list[dict[str, Any]], entities: list[Entity], rels: list[Relationship]
) -> None:
    for row in rows:
        name = first(row, "name", "asset_name")
        if name is None:
            continue
        node_id = f"asset:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="AssetInstance",
                properties=props(
                    name=first(row, "asset_name", "name"),
                    asset_category=first(row, "asset_category"),
                    lifecycleStage=first(row, "status"),
                    endOfLifeDate=first(
                        row, "disposal_date", "expected_value_after_useful_life"
                    ),
                ),
            )
        )
        _link(
            rels,
            source=node_id,
            prefix="item",
            value=first(row, "item_code", "item"),
            kind="INSTANCE_OF",
        )
        _link(
            rels,
            source=node_id,
            prefix="warehouse",
            value=first(row, "warehouse", "location"),
            kind="LOCATED_IN",
        )


def map_issues(
    rows: list[dict[str, Any]], entities: list[Entity], rels: list[Relationship]
) -> None:
    for row in rows:
        name = first(row, "name", "subject")
        if name is None:
            continue
        node_id = f"erpnextissue:{name}"
        entities.append(
            Entity(
                id=node_id,
                node_type="ErpNextIssue",
                properties=props(
                    subject=first(row, "subject", "name"),
                    status=first(row, "status", "state"),
                    priority=first(row, "priority"),
                ),
            )
        )
        _link(
            rels,
            source=node_id,
            prefix="customer",
            value=first(row, "customer", "customer_name"),
            kind="RAISED_BY",
        )
