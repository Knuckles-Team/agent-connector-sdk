"""Central-bank announcement calendar, each entry keyed by its own vintage.

A central-bank calendar (FOMC rate decisions, minutes releases, press
conferences, and the same for other central banks) schedules an
announcement for a future date and time, then sometimes reschedules it. Each
published schedule is a new vintage of the same announcement, never an
overwrite: a consumer that already cached an earlier schedule keeps it, and
a later one records the reschedule explicitly rather than silently losing
the prior value (the same revision model FRED/ALFRED uses in
:mod:`agent_connector_sdk.finance.fred_series`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from pydantic import Field

from agent_connector_sdk.finance.records import FinanceRecordBase

__all__ = [
    "CalendarIdentityConflictError",
    "CentralBankAnnouncement",
    "central_bank_calendar_from_source",
]


class CalendarIdentityConflictError(ValueError):
    """Different announcements share one legacy source identity."""


class CentralBankAnnouncement(FinanceRecordBase):
    """One scheduled central-bank announcement, as of one published vintage."""

    calendar_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    announcement_time_utc: datetime
    vintage_date: str = Field(min_length=1)


def _announcement_event_id(calendar_id: str, event_type: str, vintage: str) -> str:
    return f"{calendar_id}:{event_type}:{vintage}"


def _announcement_from_source(
    raw: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    calendar_id: str,
    license_tag: str,
    observed_at_utc: datetime,
) -> CentralBankAnnouncement:
    event_type = raw.get("event_type")
    vintage = raw.get("vintage_date")
    timestamp = raw.get("announcement_time_utc")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("calendar event type is required")
    if not isinstance(vintage, str):
        raise ValueError("calendar vintage must be a canonical date")
    try:
        if date.fromisoformat(vintage).isoformat() != vintage:
            raise ValueError
    except ValueError:
        raise ValueError("calendar vintage must be a canonical date") from None
    if not isinstance(timestamp, str) or not any(c in timestamp for c in ("T", " ")):
        raise ValueError("calendar announcement time must include a time")
    try:
        announcement_time = datetime.fromisoformat(timestamp)
        if announcement_time.tzinfo is None:
            announcement_time = announcement_time.replace(tzinfo=UTC)
        else:
            announcement_time = announcement_time.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValueError("calendar announcement time is invalid") from None
    event_id = _announcement_event_id(calendar_id, event_type, vintage)
    return CentralBankAnnouncement(
        tenant_id=tenant_id,
        source_id=source_id,
        provider=provider,
        instrument_id=calendar_id,
        source_event_id=event_id,
        event_time_utc=announcement_time,
        observed_at_utc=observed_at_utc,
        license_tag=license_tag,
        source_digest=event_id,
        calendar_id=calendar_id,
        event_type=event_type,
        announcement_time_utc=announcement_time,
        vintage_date=vintage,
    )


def central_bank_calendar_from_source(
    payload: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    calendar_id: str,
    license_tag: str,
    observed_at_utc: datetime,
) -> tuple[CentralBankAnnouncement, ...]:
    """Normalize one calendar source page; one record per published vintage.

    ``payload["events"]`` entries each carry ``event_type``,
    ``announcement_time_utc`` (ISO-8601; a naive timestamp is treated as
    UTC), and ``vintage_date`` (the date this schedule was published or
    last confirmed). A rescheduled announcement arrives as a new entry with
    the same ``event_type`` and a later ``vintage_date``; it is a distinct
    record, never a replacement of the earlier one.
    """
    raw_events = payload.get("events")
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
        raise ValueError("calendar events must be an array")
    if not all(isinstance(item, Mapping) for item in raw_events):
        raise ValueError("calendar events must be objects")
    events = tuple(
        _announcement_from_source(
            raw,
            tenant_id=tenant_id,
            source_id=source_id,
            provider=provider,
            calendar_id=calendar_id,
            license_tag=license_tag,
            observed_at_utc=observed_at_utc,
        )
        for raw in raw_events
    )
    _require_consistent_identities(events)
    return events


def _require_consistent_identities(events: tuple[CentralBankAnnouncement, ...]) -> None:
    seen: dict[str, datetime] = {}
    for event in events:
        previous = seen.get(event.source_event_id)
        if previous is not None and previous != event.announcement_time_utc:
            raise CalendarIdentityConflictError(
                "calendar page has conflicting announcement identities"
            )
        seen[event.source_event_id] = event.announcement_time_utc
