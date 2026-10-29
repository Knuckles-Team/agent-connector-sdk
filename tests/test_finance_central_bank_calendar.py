"""Central-bank announcement calendar preserves vintage and announcement time
(SCION-FINANCE-SOURCES-R001)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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


def test_each_announcement_preserves_its_scheduled_time_and_vintage() -> None:
    events = _calendar()

    assert [e.event_type for e in events] == ["rate_decision", "minutes_release"]
    assert events[0].announcement_time_utc == datetime(2026, 3, 18, 18, 0, tzinfo=UTC)
    assert events[0].vintage_date == "2025-12-01"
    assert events[0].event_time_utc == events[0].announcement_time_utc


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


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.3")
def test_same_vintage_distinct_announcements_refuse_identity_collision() -> None:
    from agent_connector_sdk.finance.central_bank_calendar import (
        CalendarIdentityConflictError,
    )

    payload = {
        "events": [
            {
                "event_type": "rate_decision",
                "announcement_time_utc": "2026-03-18T18:00:00+00:00",
                "vintage_date": "2025-12-01",
            },
            {
                "event_type": "rate_decision",
                "announcement_time_utc": "2026-04-29T18:00:00+00:00",
                "vintage_date": "2025-12-01",
            },
        ]
    }
    with pytest.raises(CalendarIdentityConflictError):
        _calendar(payload=payload)


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.3")
def test_same_instant_with_equivalent_offsets_does_not_conflict() -> None:
    payload = {
        "events": [
            {
                "event_type": "rate_decision",
                "announcement_time_utc": "2026-03-18T18:00:00+00:00",
                "vintage_date": "2025-12-01",
            },
            {
                "event_type": "rate_decision",
                "announcement_time_utc": "2026-03-18T14:00:00-04:00",
                "vintage_date": "2025-12-01",
            },
        ]
    }
    events = _calendar(payload=payload)
    assert events[0].source_event_id == events[1].source_event_id


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.9")
@pytest.mark.parametrize("events", [None, {}, "private-calendar-value", [None]])
def test_calendar_rejects_missing_or_malformed_event_arrays(events) -> None:
    with pytest.raises(ValueError) as error:
        _calendar(payload={"events": events})
    assert "private-calendar-value" not in str(error.value)
    with pytest.raises(ValueError):
        _calendar(payload={})
    assert _calendar(payload={"events": []}) == ()


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.9")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_type", None),
        ("event_type", "  "),
        ("vintage_date", "20251201"),
        ("vintage_date", "private-calendar-value"),
        ("announcement_time_utc", "2026-03-18"),
        ("announcement_time_utc", "private-calendar-value"),
        ("announcement_time_utc", "0001-01-01T00:00:00+14:00"),
    ],
)
def test_calendar_refuses_ambiguous_identity_and_time(field, value) -> None:
    record = {**_PAGE["events"][0], field: value}
    with pytest.raises(ValueError) as error:
        _calendar(payload={"events": [record]})
    assert "private-calendar-value" not in str(error.value)


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.9")
def test_calendar_normalizes_offsets_without_changing_instant() -> None:
    record = {
        **_PAGE["events"][0],
        "announcement_time_utc": "2026-03-18T14:00:00-04:00",
    }
    (event,) = _calendar(payload={"events": [record]})
    assert event.announcement_time_utc == datetime(2026, 3, 18, 18, 0, tzinfo=UTC)
    assert event.announcement_time_utc.tzinfo is UTC
