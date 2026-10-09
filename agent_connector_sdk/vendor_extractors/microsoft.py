"""Microsoft 365 vendor extractor (SDK-SOURCE-INGEST-R006.9).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.microsoft``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
calendar events and directory users become ``CalendarEvent``/``Person``
entities instead of agent-utilities' ``GraphNode`` -- the same canonical
classes the Nextcloud port uses, so M365/Nextcloud calendars and people
reconcile across sources. The client is injected through ``config`` and this
module performs no I/O of its own; all calls are tolerant -- a missing
surface yields no entities rather than an error.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "microsoft"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _nested(row: dict[str, Any], *path: str) -> Any:
    cur: Any = row
    for part in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _call(client: Any, name: str) -> list[dict[str, Any]]:
    method = getattr(client, name, None)
    try:
        return list(method() or []) if callable(method) else []
    except Exception:
        return []


def _events(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for event in _call(client, "calendar_events"):
        event_id = event.get("id")
        if not event_id:
            continue
        properties = {
            "name": event.get("subject"),
            "scheduledStart": _nested(event, "start", "dateTime"),
            "scheduledEnd": _nested(event, "end", "dateTime"),
            "eventLocation": _nested(event, "location", "displayName"),
            "externalToolId": str(event_id),
            "domain": CATEGORY,
        }
        entities.append(
            Entity(
                id=f"msevent:{event_id}",
                node_type="CalendarEvent",
                properties={
                    key: value for key, value in properties.items() if value is not None
                },
            )
        )
    return entities


def _users(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for user in _call(client, "users"):
        user_id = user.get("id")
        if not user_id:
            continue
        entities.append(
            Entity(
                id=f"msuser:{user_id}",
                node_type="Person",
                properties={
                    key: value
                    for key, value in {
                        "name": user.get("displayName"),
                        "email": user.get("mail") or user.get("userPrincipalName"),
                        "externalToolId": str(user_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )
    return entities


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    return ChangeSet(entities=tuple([*_events(client), *_users(client)]))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Microsoft 365 (calendar events + users) -> KG entities",
)
