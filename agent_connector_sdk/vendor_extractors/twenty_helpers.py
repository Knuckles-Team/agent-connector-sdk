"""Pure record-shaping helpers for the Twenty CRM extractor."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import Entity

_DOMAIN = "twenty"


def _dict_rows(rows: Any) -> list[dict[str, Any]]:
    return (
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    )


def _connection_rows(conn: Any) -> list[dict[str, Any]] | None:
    """Rows of a GraphQL connection or plain list; ``None`` when neither."""
    if isinstance(conn, dict) and isinstance(conn.get("edges"), list):
        return [
            edge["node"]
            for edge in conn["edges"]
            if isinstance(edge, dict) and edge.get("node")
        ]
    if isinstance(conn, list):
        return _dict_rows(conn)
    return None


def _records(res: Any, plural: str) -> list[dict[str, Any]]:
    """Pull records from REST ``{data:[...]}`` or GraphQL connection shapes."""
    if not isinstance(res, dict):
        return _dict_rows(res)
    data = res.get("data", res)
    if isinstance(data, dict) and plural in data:
        rows = _connection_rows(data[plural])
        if rows is not None:
            return rows
    return _dict_rows(data)


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


def _company_ref(record: dict[str, Any]) -> Any:
    return record.get("companyId") or (record.get("company") or {}).get("id")


def _person_entity(person: dict[str, Any], node_id: str, person_id: Any) -> Entity:
    return Entity(
        id=node_id,
        node_type="Person",
        properties=_props(
            name=_name(person, "name", "displayName"),
            email=_name(person, "email"),
            externalToolId=str(person_id),
            domain=_DOMAIN,
        ),
    )


def _opportunity_entity(opp: dict[str, Any], node_id: str, opp_id: Any) -> Entity:
    amount = opp.get("amount")
    return Entity(
        id=node_id,
        node_type="SalesOrder",
        properties=_props(
            name=_name(opp, "name"),
            stage=opp.get("stage"),
            amount=amount.get("amountMicros") if isinstance(amount, dict) else amount,
            externalToolId=str(opp_id),
            domain=_DOMAIN,
        ),
    )
