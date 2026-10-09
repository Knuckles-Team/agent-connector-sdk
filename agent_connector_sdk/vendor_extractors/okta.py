"""Okta identity vendor extractor (SDK-SOURCE-INGEST-R006.18).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.okta`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`: users
become ``IdentityUser`` entities, groups become ``IdentityGroup`` entities
(``MEMBER_OF_GROUP`` relationships from each member), and apps become
``Application`` entities. Every entity carries ``externalToolId`` +
``domain="okta"``. The client is injected through ``config`` and this module
performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "okta"
_DOMAIN = "okta"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


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
    if isinstance(result, list | tuple):
        return list(result)
    if isinstance(result, dict):
        for key in ("value", "results", "items", "data"):
            value = result.get(key)
            if isinstance(value, list):
                return list(value)
    return []


def _profile(row: dict[str, Any], *keys: str) -> Any:
    profile = row.get("profile") if isinstance(row, dict) else None
    if isinstance(profile, dict):
        for key in keys:
            if profile.get(key):
                return profile[key]
    return _first(row, *keys)


def _props(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _user_entities(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for user in _call(client, "list_users"):
        user_id = _first(user, "id")
        if not user_id:
            continue
        entities.append(
            Entity(
                id=f"okta_user:{user_id}",
                node_type="IdentityUser",
                properties=_props(
                    name=_profile(user, "login", "email", "displayName"),
                    email=_profile(user, "email"),
                    status=_first(user, "status"),
                    externalToolId=str(user_id),
                    domain=_DOMAIN,
                ),
            )
        )
    return entities


def _group_member_relationships(
    client: Any, group_id: Any, group_node: str
) -> list[Relationship]:
    relationships: list[Relationship] = []
    for member in _call(client, "list_group_members", group_id):
        member_id = _first(member, "id")
        if member_id:
            relationships.append(
                Relationship(
                    source=f"okta_user:{member_id}",
                    target=group_node,
                    relationship="MEMBER_OF_GROUP",
                )
            )
    return relationships


def _group_entities_and_relationships(
    client: Any,
) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for group in _call(client, "list_groups"):
        group_id = _first(group, "id")
        if not group_id:
            continue
        group_node = f"okta_group:{group_id}"
        entities.append(
            Entity(
                id=group_node,
                node_type="IdentityGroup",
                properties=_props(
                    name=_profile(group, "name"),
                    externalToolId=str(group_id),
                    domain=_DOMAIN,
                ),
            )
        )
        relationships.extend(_group_member_relationships(client, group_id, group_node))
    return entities, relationships


def _app_entities(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for app in _call(client, "list_apps"):
        app_id = _first(app, "id")
        if not app_id:
            continue
        entities.append(
            Entity(
                id=f"okta_app:{app_id}",
                node_type="Application",
                properties=_props(
                    name=_first(app, "label", "name"),
                    status=_first(app, "status"),
                    externalToolId=str(app_id),
                    domain=_DOMAIN,
                ),
            )
        )
    return entities


def extract(config: Any) -> ChangeSet:
    """Extract Okta users/groups/apps into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = list(_user_entities(client))
    relationships: list[Relationship] = []

    group_entities, group_relationships = _group_entities_and_relationships(client)
    entities.extend(group_entities)
    relationships.extend(group_relationships)

    entities.extend(_app_entities(client))

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="Okta identity (users/groups/apps) -> KG"
)
