"""Weather quality identity and units come from explicit host approval."""

from datetime import UTC, datetime

import pytest

from agent_connector_sdk.earth_observations.records import (
    Place,
    Region,
    WeatherObservation,
)
from agent_connector_sdk.earth_observations.weather_location import (
    WeatherLocation,
    WeatherQuality,
    _located_records,
)


def test_admitted_quality_adds_ontology_edge_and_approved_unit():
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    row = WeatherObservation(
        tenant_id="tenant",
        source_id="weather",
        provider="noaa_hourly",
        source_event_id="event",
        event_time_utc=timestamp,
        observed_at_utc=timestamp,
        license_tag="approved",
        source_digest="digest",
        place_id="station",
        variable="temperature",
        value=2.0,
        unit="°C",
        latitude=1.0,
        longitude=2.0,
    )
    location = WeatherLocation(
        Place(
            place_id="station",
            name="Station",
            region_id="region",
            latitude=1.0,
            longitude=2.0,
        ),
        Region(region_id="region", name="Region", kind="operator"),
    )
    quality = WeatherQuality(
        "temperature", "Air temperature", "temperature", "°C", "Cel"
    )
    records, relationships = _located_records((row,), location, quality)
    assert records[0]["unit_code"] == "Cel"
    assert any(record["node_type"] == "QualityTerm" for record in records)
    assert any(edge["relationship"] == "observedQuality" for edge in relationships)
    with pytest.raises(ValueError, match="quality differs"):
        _located_records(
            (row,), location, WeatherQuality("q", "Other", "humidity", "%", "%")
        )
