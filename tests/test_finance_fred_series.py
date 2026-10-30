"""FS-04: FRED/ALFRED vintage is preserved; a revision is a new record."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from scion_sdk.finance.fred_series import (
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


@pytest.mark.spec("SCION-FINANCE-SOURCES-R005")
@pytest.mark.spec("SCION-FINANCE-SOURCES-R005.1")
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


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.1")
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e999"])
def test_nonfinite_values_are_rejected(value: str) -> None:
    page = {
        "observations": [
            {"date": "2025-11-01", "realtime_start": "2025-12-05", "value": value}
        ]
    }
    with pytest.raises(ValidationError, match="finite"):
        _series(payload=page)
    valid = _series()[0].model_dump()
    valid["value"] = float(value)
    with pytest.raises(ValidationError, match="finite"):
        MacroSeriesObservation(**valid)


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.4")
@pytest.mark.parametrize("value", [None, "invalid", {}, 1])
def test_observation_page_requires_an_array(value: object) -> None:
    with pytest.raises(ValueError, match="observations must be an array"):
        _series(payload={"observations": value})
    with pytest.raises(ValueError, match="observations must be an array"):
        _series(payload={})
    assert _series(payload={"observations": []}) == ()


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.5")
@pytest.mark.parametrize(
    "field,value",
    [
        ("date", "20251101"),
        ("realtime_start", "20251205"),
        ("date", "2025-W44-6"),
        ("realtime_start", "2025-12-05T00:00:00"),
        ("date", None),
    ],
)
def test_fred_observation_identity_requires_canonical_dates(
    field: str, value: object
) -> None:
    observation = dict(_PAGE["observations"][0])
    observation[field] = value
    with pytest.raises(ValueError):
        _series(payload={"observations": [observation]})
    record = _series()[0]
    assert record.source_event_id == "UNRATE:2025-11-01:2025-12-05"
    assert record.event_time_utc == datetime(2025, 11, 1, tzinfo=UTC)


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.6")
@pytest.mark.parametrize("other_value", ["3.7", "9.1"])
def test_fred_page_refuses_duplicate_observation_identities(other_value: str) -> None:
    first = dict(_PAGE["observations"][0])
    second = {**first, "value": other_value}
    with pytest.raises(ValueError, match="duplicate observation identities"):
        _series(payload={"observations": [first, second]})
    assert len(_series()) == 2
