"""Nextcloud vendor extractor -- calendar events + contacts (SDK-SOURCE-INGEST-R006.16).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.nextcloud``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
CalDAV calendar events and CardDAV contacts become ``CalendarEvent``/
``Person`` entities instead of agent-utilities' ``GraphNode`` -- the same
canonical classes the Microsoft 365 port uses, so Nextcloud and M365 calendars
and people reconcile across sources. Documents flow through the document
pipeline, not here. The client is injected through ``config`` and this module
performs no I/O of its own; all calls are tolerant.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "nextcloud"


def _get(config: Any, key: str) -> Any:
    if isinstance(config, dict):
        return config.get(key)
    return getattr(config, key, None)


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
        return list(method(*args) or [])
    except Exception:
        return []


def _events(client: Any, seen: set[str]) -> list[Entity]:
    entities: list[Entity] = []
    for calendar in _call(client, "list_calendars"):
        calendar_url = _first(calendar, "url", "href")
        if not calendar_url:
            continue
        for event in _call(client, "list_events", calendar_url):
            uid = _first(event, "uid", "id", "href")
            if not uid:
                continue
            node_id = f"event:{uid}"
            if node_id in seen:
                continue
            seen.add(node_id)
            properties = {
                "name": _first(event, "summary", "title", "name"),
                "scheduledStart": _first(event, "start", "dtstart", "DTSTART"),
                "scheduledEnd": _first(event, "end", "dtend", "DTEND"),
                "eventLocation": _first(event, "location", "LOCATION"),
                "calendar": calendar_url,
                "externalToolId": str(uid),
                "domain": CATEGORY,
            }
            entities.append(
                Entity(
                    id=node_id,
                    node_type="CalendarEvent",
                    properties={
                        key: value
                        for key, value in properties.items()
                        if value is not None
                    },
                )
            )
    return entities


def _contacts(client: Any, seen: set[str]) -> list[Entity]:
    entities: list[Entity] = []
    for address_book in _call(client, "list_address_books"):
        book_url = _first(address_book, "url", "href")
        if not book_url:
            continue
        for contact in _call(client, "list_contacts", book_url):
            uid = _first(contact, "uid", "id", "href")
            name = _first(contact, "fn", "full_name", "name")
            if not (uid and name):
                continue
            node_id = f"contact:{uid}"
            if node_id in seen:
                continue
            seen.add(node_id)
            entities.append(
                Entity(
                    id=node_id,
                    node_type="Person",
                    properties={
                        key: value
                        for key, value in {
                            "name": name,
                            "email": _first(contact, "email", "EMAIL"),
                            "externalToolId": str(uid),
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
    seen: set[str] = set()
    entities = [*_events(client, seen), *_contacts(client, seen)]
    return ChangeSet(entities=tuple(entities))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Nextcloud calendar events + contacts -> KG entities",
)
