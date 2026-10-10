"""Normalized earth-observation record identity and place/region rules."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_connector_sdk.earth_observations.records import (
    EARTH_OBSERVATION_SCHEMA_VERSION,
    EarthObservationRecordBase,
    OrganismObservation,
    Place,
    Region,
    WeatherEvent,
    WeatherObservation,
)

_NOW = datetime(2026, 1, 2, tzinfo=UTC)


def _base_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "tenant_id": "tenant-1",
        "source_id": "source-1",
        "provider": "fixture-vendor",
        "source_event_id": "event-1",
        "event_time_utc": _NOW,
        "observed_at_utc": _NOW,
        "license_tag": "open",
        "source_digest": "digest-1",
    }
    fields.update(overrides)
    return fields


@pytest.mark.spec("SDK-SOURCE-INGEST-R008")
def test_organism_observation_carries_schema_version_and_base_fields() -> None:
    observation = OrganismObservation(
        **_base_fields(),
        taxon_id="GBIF:5231190",
        scientific_name="Panthera leo",
        place_id="place-1",
        latitude=1.0,
        longitude=2.0,
        individual_count=2,
        basis_of_record="HUMAN_OBSERVATION",
    )
    assert isinstance(observation, EarthObservationRecordBase)
    assert observation.schema_version == EARTH_OBSERVATION_SCHEMA_VERSION


@pytest.mark.spec("SDK-SOURCE-INGEST-R008")
def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        WeatherObservation(
            **_base_fields(event_time_utc=datetime(2026, 1, 2)),
            place_id="station-1",
            variable="temperature",
            value=10.0,
            unit="celsius",
        )


@pytest.mark.spec("SDK-SOURCE-INGEST-R008")
def test_weather_event_names_its_weather_system() -> None:
    event = WeatherEvent(
        **_base_fields(),
        weather_system_id="noaa:storm-42",
        weather_system_name="Storm Forty Two",
        place_id="station-1",
        event_type="tornado",
        severity="EF2",
    )
    assert event.weather_system_name == "Storm Forty Two"


def test_place_is_located_in_its_declared_region() -> None:
    region = Region(region_id="region-1", name="Great Plains", kind="climate_region")
    station = Place(
        place_id="station-1",
        name="Station One",
        region_id="region-1",
        latitude=36.0,
        longitude=-98.0,
    )
    assert station.is_located_in(region)


def test_place_rejects_latitude_out_of_range() -> None:
    with pytest.raises(ValidationError):
        Place(
            place_id="station-1",
            name="Station One",
            region_id="region-1",
            latitude=91.0,
            longitude=0.0,
        )
