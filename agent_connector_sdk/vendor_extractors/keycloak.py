"""Keycloak vendor extractor (SDK-SOURCE-INGEST-R006.14).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.keycloak``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
a realm's users, groups, and clients become ``IdentityUser``/
``IdentityGroup``/``Application`` entities instead of agent-utilities'
``GraphNode``. The realm comes from ``config['realm']`` (default
``master``). The client is injected through ``config`` and this module
performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "keycloak"


def _get(config: Any, key: str, default: Any = None) -> Any:
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _first(row: Any, *keys: str) -> Any:
    if not isinstance(row, dict):
        return None
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _call(client: Any, name: str, *args: Any) -> list[Any]:
    method = getattr(client, name, None)
    if not callable(method):
        return []
    try:
        result = method(*args)
    except Exception:
        return []
    return list(result) if isinstance(result, (list, tuple)) else []


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    realm = _get(config, "realm", "master")

    entities: list[Entity] = []
    for user in _call(client, "list_users", realm):
        user_id = _first(user, "id", "username")
        if not user_id:
            continue
        entities.append(
            Entity(
                id=f"kc_user:{user_id}",
                node_type="IdentityUser",
                properties={
                    key: value
                    for key, value in {
                        "name": _first(user, "username", "email"),
                        "email": _first(user, "email"),
                        "enabled": _first(user, "enabled"),
                        "realm": realm,
                        "externalToolId": str(user_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )

    for group in _call(client, "list_groups", realm) or _call(
        client, "get_groups", realm
    ):
        group_id = _first(group, "id", "name")
        if not group_id:
            continue
        entities.append(
            Entity(
                id=f"kc_group:{group_id}",
                node_type="IdentityGroup",
                properties={
                    key: value
                    for key, value in {
                        "name": _first(group, "name"),
                        "realm": realm,
                        "externalToolId": str(group_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )

    for client_row in _call(client, "list_clients", realm) or _call(
        client, "get_clients", realm
    ):
        client_id = _first(client_row, "id", "clientId")
        if not client_id:
            continue
        entities.append(
            Entity(
                id=f"kc_client:{client_id}",
                node_type="Application",
                properties={
                    key: value
                    for key, value in {
                        "name": _first(client_row, "clientId", "name"),
                        "realm": realm,
                        "externalToolId": str(client_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )

    return ChangeSet(entities=tuple(entities))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Keycloak realm (users/groups/clients) -> KG entities",
)
