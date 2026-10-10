"""SDK-SOURCE-INGEST-R006.16: the Nextcloud vendor extractor port."""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.nextcloud import CATEGORY, extract


class _FakeClient:
    def __init__(
        self,
        calendars: object,
        events_by_calendar: dict[str, object],
        address_books: object,
        contacts_by_book: dict[str, object],
    ) -> None:
        self._calendars = calendars
        self._events_by_calendar = events_by_calendar
        self._address_books = address_books
        self._contacts_by_book = contacts_by_book

    def list_calendars(self) -> object:
        return self._calendars

    def list_events(self, calendar_url: str) -> object:
        return self._events_by_calendar.get(calendar_url, [])

    def list_address_books(self) -> object:
        return self._address_books

    def list_contacts(self, book_url: str) -> object:
        return self._contacts_by_book.get(book_url, [])


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.16")
def test_extract_returns_calendar_event_and_person_entities() -> None:
    config = {
        "client": _FakeClient(
            calendars=[{"url": "/cal/personal"}],
            events_by_calendar={"/cal/personal": [{"uid": "e1", "summary": "Standup"}]},
            address_books=[{"url": "/addr/default"}],
            contacts_by_book={
                "/addr/default": [{"uid": "c1", "fn": "Jo", "email": "jo@example.com"}]
            },
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 2
    event, contact = result.entities
    assert isinstance(event, Entity)
    assert event.id == "event:e1"
    assert event.node_type == "CalendarEvent"
    assert event.properties["name"] == "Standup"
    assert contact.id == "contact:c1"
    assert contact.node_type == "Person"
    assert contact.properties["email"] == "jo@example.com"
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.16")
def test_extract_deduplicates_events_seen_across_calendars() -> None:
    config = {
        "client": _FakeClient(
            calendars=[{"url": "/cal/a"}, {"url": "/cal/b"}],
            events_by_calendar={
                "/cal/a": [{"uid": "e1", "summary": "Standup"}],
                "/cal/b": [{"uid": "e1", "summary": "Standup (dup)"}],
            },
            address_books=[],
            contacts_by_book={},
        )
    }

    result = extract(config)

    assert len(result.entities) == 1


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.16")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.16")
def test_extract_returns_an_empty_change_set_when_list_calendars_raises() -> None:
    class _BrokenClient:
        def list_calendars(self) -> object:
            raise RuntimeError("down")

        def list_address_books(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.16")
def test_nextcloud_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
