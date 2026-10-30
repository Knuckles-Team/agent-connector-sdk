"""Emerald-Exchange vendor extractor (SCION-SOURCE-INGEST-R006.12).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.emerald``
onto this SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`:
the trading account state becomes canonical quant entities -- account ->
``Account``, a synthetic ``Portfolio``, open positions -> ``Position`` with a
``HELD_IN`` relationship to the portfolio -- instead of agent-utilities'
``GraphNode``/``EnrichmentEdge``. The backend is injected through ``config``;
its read methods return dataclasses, so values are read tolerantly (object
attribute or dict key). Read-only: no orders here.
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity, Relationship
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "emerald"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _call(client: Any, name: str) -> Any:
    method = getattr(client, name, None)
    try:
        return method() if callable(method) else None
    except Exception:
        return None


def _props(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _account_entities(account: Any, exchange: str, portfolio_id: str) -> list[Entity]:
    entities = [
        Entity(
            id=portfolio_id,
            node_type="Portfolio",
            properties={
                "exchange": exchange,
                "externalToolId": exchange,
                "domain": CATEGORY,
            },
        )
    ]
    if account is None:
        return entities
    entities.append(
        Entity(
            id=f"emerald:account:{exchange}",
            node_type="Account",
            properties=_props(
                {
                    "equity": _attr(account, "equity"),
                    "cash": _attr(account, "cash"),
                    "buying_power": _attr(account, "buying_power"),
                    "currency": _attr(account, "currency"),
                    "externalToolId": f"account:{exchange}",
                    "domain": CATEGORY,
                }
            ),
        )
    )
    return entities


def _position_entity(position: Any, exchange: str, symbol: Any) -> Entity:
    return Entity(
        id=f"emerald:pos:{exchange}:{symbol}",
        node_type="Position",
        properties=_props(
            {
                "symbol": symbol,
                "qty": _attr(position, "qty"),
                "avg_entry_price": _attr(position, "avg_entry_price"),
                "current_price": _attr(position, "current_price"),
                "unrealized_pnl": _attr(position, "unrealized_pnl"),
                "side": _attr(position, "side"),
                "externalToolId": f"{exchange}:{symbol}",
                "domain": CATEGORY,
            }
        ),
    )


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    account = _call(client, "get_account")
    exchange = str(_attr(account, "exchange", "emerald") or "emerald")
    portfolio_id = f"emerald:portfolio:{exchange}"
    entities = _account_entities(account, exchange, portfolio_id)
    relationships: list[Relationship] = []

    positions = _call(client, "get_positions") or []
    for position in positions if isinstance(positions, list) else []:
        symbol = _attr(position, "symbol")
        if not symbol:
            continue
        entity = _position_entity(position, exchange, symbol)
        entities.append(entity)
        relationships.append(
            Relationship(source=entity.id, target=portfolio_id, relationship="HELD_IN")
        )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Emerald-Exchange (account/portfolio/positions) -> KG entities",
)
