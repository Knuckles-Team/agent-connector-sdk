"""FS-04: FRED/ALFRED vintage is preserved; a revision is a new record."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from agent_connector_sdk.finance.fred_series import (
    MacroSeriesObservation,
    MissingFredValueError,
    macro_series_from_fred,
)

_OBSERVED = datetime(2026, 1, 2, tzinfo=UTC)

_PAGE = {
    "observations": [
        {"date": "2025-11-01", "realtime_start": "2025-12-05", "value": "3.7"},
        {"date": "2025-12-01", "realtime_start": "2026-01-05", "value": "3.8"},
    ]
}


def _series(**overrides: object) -> tuple[MacroSeriesObservation, ...]:
    fields: dict[str, object] = {
        "payload": _PAGE,
        "tenant_id": "tenant-1",
        "source_id": "fred",
        "provider": "fred",
        "series_id": "UNRATE",
        "license_tag": "open",
        "observed_at_utc": _OBSERVED,
    }
    fields.update(overrides)
    return macro_series_from_fred(**fields)


def test_each_observation_preserves_its_own_vintage_date() -> None:
    observations = _series()

    assert [o.observation_date for o in observations] == [
        date(2025, 11, 1),
        date(2025, 12, 1),
    ]
    assert [o.vintage_date for o in observations] == [
        date(2025, 12, 5),
        date(2026, 1, 5),
    ]
    assert observations[0].value == 3.7


def test_a_later_vintage_of_the_same_period_is_a_distinct_record() -> None:
    revised_page = {
        "observations": [
            *_PAGE["observations"],
            {"date": "2025-11-01", "realtime_start": "2026-02-01", "value": "3.6"},
        ]
    }
    observations = _series(payload=revised_page)

    first, revision = observations[0], observations[2]
    assert first.observation_date == revision.observation_date
    assert first.source_event_id != revision.source_event_id
    assert first.value != revision.value


def test_a_missing_value_refuses_rather_than_fabricating_zero() -> None:
    missing_page = {
        "observations": [
            {"date": "2025-11-01", "realtime_start": "2025-12-05", "value": "."}
        ]
    }
    with pytest.raises(MissingFredValueError):
        _series(payload=missing_page)


def test_vintage_before_its_own_observation_period_is_rejected() -> None:
    with pytest.raises(ValidationError, match="vintage_date"):
        MacroSeriesObservation(
            tenant_id="tenant-1",
            source_id="fred",
            provider="fred",
            instrument_id="UNRATE",
            source_event_id="UNRATE:2025-11-01:2025-10-01",
            event_time_utc=datetime(2025, 11, 1, tzinfo=UTC),
            observed_at_utc=_OBSERVED,
            license_tag="open",
            source_digest="UNRATE:2025-11-01:2025-10-01",
            series_id="UNRATE",
            observation_date=date(2025, 11, 1),
            vintage_date=date(2025, 10, 1),
            value=3.7,
        )
