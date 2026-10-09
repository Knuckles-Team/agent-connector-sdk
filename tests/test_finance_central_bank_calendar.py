"""Central-bank announcement calendar preserves vintage and announcement time
(SDK-FINANCE-SOURCES-R001)."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime

from agent_connector_sdk.finance.central_bank_calendar import (
    CentralBankAnnouncement,
    central_bank_calendar_from_source,
)

_OBSERVED = datetime(2026, 1, 2, tzinfo=UTC)

_PAGE = {
    "events": [
        {
            "event_type": "rate_decision",
            "announcement_time_utc": "2026-03-18T18:00:00+00:00",
            "vintage_date": "2025-12-01",
        },
        {
            "event_type": "minutes_release",
            "announcement_time_utc": "2026-04-08T18:00:00+00:00",
            "vintage_date": "2025-12-01",
        },
    ]
}


def _calendar(**overrides: object) -> tuple[CentralBankAnnouncement, ...]:
    fields: dict[str, object] = {
        "payload": _PAGE,
        "tenant_id": "tenant-1",
        "source_id": "fomc",
        "provider": "federal-reserve",
        "calendar_id": "FOMC",
        "license_tag": "open",
        "observed_at_utc": _OBSERVED,
    }
    fields.update(overrides)
    return central_bank_calendar_from_source(**fields)


@pytest.mark.spec("SDK-FINANCE-SOURCES-R001", "SDK-FINANCE-SOURCES-R005")
def test_each_announcement_preserves_its_scheduled_time_and_vintage() -> None:
    events = _calendar()

    assert [e.event_type for e in events] == ["rate_decision", "minutes_release"]
    assert events[0].announcement_time_utc == datetime(2026, 3, 18, 18, 0, tzinfo=UTC)
    assert events[0].vintage_date == "2025-12-01"
    assert events[0].event_time_utc == events[0].announcement_time_utc


@pytest.mark.spec("SDK-FINANCE-SOURCES-R001", "SDK-FINANCE-SOURCES-R005")
def test_a_reschedule_is_a_distinct_vintage_record_not_an_overwrite() -> None:
    rescheduled_page = {
        "events": [
            *_PAGE["events"],
            {
                "event_type": "rate_decision",
                "announcement_time_utc": "2026-03-19T18:00:00+00:00",
                "vintage_date": "2026-02-01",
            },
        ]
    }
    events = _calendar(payload=rescheduled_page)

    rate_decisions = [e for e in events if e.event_type == "rate_decision"]
    assert len(rate_decisions) == 2
    assert rate_decisions[0].announcement_time_utc == datetime(
        2026, 3, 18, 18, 0, tzinfo=UTC
    )
    assert rate_decisions[1].announcement_time_utc == datetime(
        2026, 3, 19, 18, 0, tzinfo=UTC
    )
    assert rate_decisions[0].source_event_id != rate_decisions[1].source_event_id


@pytest.mark.spec("SDK-FINANCE-SOURCES-R001", "SDK-FINANCE-SOURCES-R005")
def test_a_naive_announcement_time_is_treated_as_utc() -> None:
    naive_page = {
        "events": [
            {
                "event_type": "press_conference",
                "announcement_time_utc": "2026-03-18T18:30:00",
                "vintage_date": "2025-12-01",
            }
        ]
    }
    events = _calendar(payload=naive_page)

    assert events[0].announcement_time_utc.tzinfo is UTC


def test_calendar_id_becomes_the_instrument_id() -> None:
    events = _calendar()
    assert all(e.instrument_id == "FOMC" for e in events)


def test_empty_events_yields_no_records() -> None:
    assert _calendar(payload={"events": []}) == ()
