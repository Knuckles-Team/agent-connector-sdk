"""Normalized occurrence, weather and place/region record shapes.

``SDK-SOURCE-INGEST-R008`` calls for adapters that ingest GBIF and
iNaturalist occurrence records as ``OrganismObservation``, NOAA GHCN/ISD and
Open-Meteo data as ``WeatherObservation``, and NOAA storm events as
``WeatherEvent`` occurring in a ``WeatherSystem``, with weather stations
represented as ``Place`` located in a ``Region``. This module normalizes
those shapes; the vendor-specific GBIF, iNaturalist and NOAA/Open-Meteo
source adapters that produce them are a follow-up slice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
EARTH_OBSERVATION_SCHEMA_VERSION = "agent-connector-sdk.earth-observations/1"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


class Region(_Frozen):
    """A named geographic region a ``Place`` can be located in."""

    region_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)


class Place(_Frozen):
    """A located point, such as a weather station, located in a ``Region``."""

    place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)

    def is_located_in(self, region: Region) -> bool:
        """Whether this place's declared region matches ``region``."""
        return self.region_id == region.region_id


class EarthObservationRecordBase(_Frozen):
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

    @model_validator(mode="after")
    def _timestamps_are_utc(self) -> Self:
        _require_utc(self.event_time_utc, field_name="event_time_utc")
        _require_utc(self.observed_at_utc, field_name="observed_at_utc")
        return self


class OrganismObservation(EarthObservationRecordBase):
    """One GBIF or iNaturalist occurrence record for a taxon at a place."""

    taxon_id: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    individual_count: int = Field(ge=0, default=1)
    basis_of_record: str = Field(min_length=1)


class WeatherObservation(EarthObservationRecordBase):
    """One NOAA GHCN/ISD or Open-Meteo reading at a station ``Place``."""

    place_id: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)


class WeatherEvent(EarthObservationRecordBase):
    """One NOAA storm event occurring in a named ``WeatherSystem``."""

    weather_system_id: str = Field(min_length=1)
    weather_system_name: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
