"""Microsoft 365 vendor extractor (SCION-SOURCE-INGEST-R006.9).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.microsoft``
onto this SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`:
calendar events and directory users become ``CalendarEvent``/``Person``
entities instead of agent-utilities' ``GraphNode`` -- the same canonical
classes the Nextcloud port uses, so M365/Nextcloud calendars and people
reconcile across sources. The client is injected through ``config`` and this
module performs no I/O of its own; all calls are tolerant -- a missing
surface yields no entities rather than an error.
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity
from scion_sdk.vendor_extractors._extract_common import _client_changeset, _entity_of
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "microsoft"


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
        entities.append(_entity_of(f"msevent:{event_id}", "CalendarEvent", properties))
    return entities


def _users(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for user in _call(client, "users"):
        user_id = user.get("id")
        if not user_id:
            continue
        fields = {
            "name": user.get("displayName"),
            "email": user.get("mail") or user.get("userPrincipalName"),
            "externalToolId": str(user_id),
            "domain": CATEGORY,
        }
        entities.append(_entity_of(f"msuser:{user_id}", "Person", fields))
    return entities


def extract(config: Any) -> ChangeSet:
    return _client_changeset(config, lambda client: [*_events(client), *_users(client)])


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Microsoft 365 (calendar events + users) -> KG entities",
)
