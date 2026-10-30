"""Normalized occurrence, weather and place/region record shapes.

``SCION-SOURCE-INGEST-R008`` calls for adapters that ingest GBIF and
iNaturalist occurrence records as ``OrganismObservation``, NOAA GHCN/ISD and
Open-Meteo data as ``WeatherObservation``, and NOAA storm events as
``WeatherEvent`` occurring in a ``WeatherSystem``, with weather stations
represented as ``Place`` located in a ``Region``. This module normalizes
those shapes; host-admitted GBIF and iNaturalist occurrence sources live
in this package. Bounded NOAA and Open-Meteo hourly temperatures are
available; NOAA daily extrema and broader storm acceptance remain open.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from scion_sdk._utc_records import _FrozenRecord, _UtcTimestampedRecord

__all__ = [
    "EARTH_OBSERVATION_SCHEMA_VERSION",
    "EarthObservationRecordBase",
    "OrganismObservation",
    "Place",
    "Region",
    "WeatherEvent",
    "WeatherObservation",
]

#: Version of the SDK-side normalized earth-observation record shapes.
EARTH_OBSERVATION_SCHEMA_VERSION = "scion-sdk.earth-observations/1"


class Region(_FrozenRecord):
    """A named geographic region a ``Place`` can be located in."""

    region_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)


class Place(_FrozenRecord):
    """A located point, such as a weather station, located in a ``Region``."""

    place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)

    def is_located_in(self, region: Region) -> bool:
        """Whether this place's declared region matches ``region``."""
        return self.region_id == region.region_id


class EarthObservationRecordBase(_UtcTimestampedRecord):
    """Fields every normalized earth-observation source record carries."""

    tenant_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    event_time_utc: datetime
    observed_at_utc: datetime
    schema_version: str = EARTH_OBSERVATION_SCHEMA_VERSION
    license_tag: str = Field(min_length=1)
    source_digest: str = Field(min_length=1)


class OrganismObservation(EarthObservationRecordBase):
    """One GBIF or iNaturalist occurrence record for a taxon at a place."""

    taxon_id: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    individual_count: int | None = Field(ge=0, default=None)
    basis_of_record: str = Field(min_length=1)


class WeatherObservation(EarthObservationRecordBase):
    """One NOAA GHCN/ISD or Open-Meteo reading at a station ``Place``."""

    place_id: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)


class WeatherEvent(EarthObservationRecordBase):
    """One NOAA storm event occurring in a named ``WeatherSystem``."""

    weather_system_id: str = Field(min_length=1)
    weather_system_name: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
