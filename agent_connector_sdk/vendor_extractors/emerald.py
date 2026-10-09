"""Emerald-Exchange vendor extractor (SDK-SOURCE-INGEST-R006.12).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.emerald``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
the trading account state becomes canonical quant entities -- account ->
``Account``, a synthetic ``Portfolio``, open positions -> ``Position`` with a
``HELD_IN`` relationship to the portfolio -- instead of agent-utilities'
``GraphNode``/``EnrichmentEdge``. The backend is injected through ``config``;
its read methods return dataclasses, so values are read tolerantly (object
attribute or dict key). Read-only: no orders here.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

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


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    account = _call(client, "get_account")
    exchange = str(_attr(account, "exchange", "emerald") or "emerald")
    portfolio_id = f"emerald:portfolio:{exchange}"
    entities.append(
        Entity(
            id=portfolio_id,
            node_type="Portfolio",
            properties={
                "exchange": exchange,
                "externalToolId": exchange,
                "domain": CATEGORY,
            },
        )
    )
    if account is not None:
        entities.append(
            Entity(
                id=f"emerald:account:{exchange}",
                node_type="Account",
                properties={
                    key: value
                    for key, value in {
                        "equity": _attr(account, "equity"),
                        "cash": _attr(account, "cash"),
                        "buying_power": _attr(account, "buying_power"),
                        "currency": _attr(account, "currency"),
                        "externalToolId": f"account:{exchange}",
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )

    positions = _call(client, "get_positions") or []
    for position in positions if isinstance(positions, list) else []:
        symbol = _attr(position, "symbol")
        if not symbol:
            continue
        position_id = f"emerald:pos:{exchange}:{symbol}"
        entities.append(
            Entity(
                id=position_id,
                node_type="Position",
                properties={
                    key: value
                    for key, value in {
                        "symbol": symbol,
                        "qty": _attr(position, "qty"),
                        "avg_entry_price": _attr(position, "avg_entry_price"),
                        "current_price": _attr(position, "current_price"),
                        "unrealized_pnl": _attr(position, "unrealized_pnl"),
                        "side": _attr(position, "side"),
                        "externalToolId": f"{exchange}:{symbol}",
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )
        relationships.append(
            Relationship(
                source=position_id, target=portfolio_id, relationship="HELD_IN"
            )
        )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Emerald-Exchange (account/portfolio/positions) -> KG entities",
)
