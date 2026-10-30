"""Keycloak vendor extractor (SCION-SOURCE-INGEST-R006.14).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.keycloak``
onto this SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`:
a realm's users, groups, and clients become ``IdentityUser``/
``IdentityGroup``/``Application`` entities instead of agent-utilities'
``GraphNode``. The realm comes from ``config['realm']`` (default
``master``). The client is injected through ``config`` and this module
performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

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


_Spec = tuple[str, str | None, tuple[str, ...], str, str, dict[str, tuple[str, ...]]]

_KINDS: list[_Spec] = [
    (
        "list_users",
        None,
        ("id", "username"),
        "kc_user",
        "IdentityUser",
        {
            "name": ("username", "email"),
            "email": ("email",),
            "enabled": ("enabled",),
        },
    ),
    (
        "list_groups",
        "get_groups",
        ("id", "name"),
        "kc_group",
        "IdentityGroup",
        {"name": ("name",)},
    ),
    (
        "list_clients",
        "get_clients",
        ("id", "clientId"),
        "kc_client",
        "Application",
        {"name": ("clientId", "name")},
    ),
]


def _entities(client: Any, realm: Any, spec: _Spec) -> list[Entity]:
    """Entities for one Keycloak record kind."""
    method, fallback, id_keys, prefix, node_type, fields = spec
    rows = _call(client, method, realm)
    if not rows and fallback:
        rows = _call(client, fallback, realm)
    entities: list[Entity] = []
    for row in rows:
        row_id = _first(row, *id_keys)
        if not row_id:
            continue
        candidates = {name: _first(row, *keys) for name, keys in fields.items()}
        candidates.update(realm=realm, externalToolId=str(row_id), domain=CATEGORY)
        entities.append(
            Entity(
                id=f"{prefix}:{row_id}",
                node_type=node_type,
                properties={k: v for k, v in candidates.items() if v is not None},
            )
        )
    return entities


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    realm = _get(config, "realm", "master")
    entities: list[Entity] = []
    for spec in _KINDS:
        entities.extend(_entities(client, realm, spec))
    return ChangeSet(entities=tuple(entities))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Keycloak realm (users/groups/clients) -> KG entities",
)
