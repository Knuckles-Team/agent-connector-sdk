"""SDK-SOURCE-INGEST-R006.9: the Microsoft 365 vendor extractor port."""

from __future__ import annotations

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.microsoft import CATEGORY, extract


class _FakeClient:
    def __init__(self, events: object, users: object) -> None:
        self._events = events
        self._users = users

    def calendar_events(self) -> object:
        return self._events

    def users(self) -> object:
        return self._users


def test_extract_returns_calendar_event_and_person_entities() -> None:
    config = {
        "client": _FakeClient(
            events=[
                {
                    "id": "e1",
                    "subject": "Standup",
                    "start": {"dateTime": "2026-01-01T09:00:00"},
                    "end": {"dateTime": "2026-01-01T09:15:00"},
                    "location": {"displayName": "Room 1"},
                }
            ],
            users=[{"id": "u1", "displayName": "Jo", "mail": "jo@example.com"}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 2
    event, user = result.entities
    assert isinstance(event, Entity)
    assert event.id == "msevent:e1"
    assert event.node_type == "CalendarEvent"
    assert event.properties["scheduledStart"] == "2026-01-01T09:00:00"
    assert event.properties["eventLocation"] == "Room 1"
    assert user.id == "msuser:u1"
    assert user.node_type == "Person"
    assert user.properties["email"] == "jo@example.com"
    assert result.relationships == ()


def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


def test_extract_returns_an_empty_change_set_when_calendar_events_raises() -> None:
    class _BrokenClient:
        def calendar_events(self) -> object:
            raise RuntimeError("down")

        def users(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


def test_microsoft_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
