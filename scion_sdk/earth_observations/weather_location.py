"""Host-admitted place and region records for weather streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scion_sdk.earth_observations.records import (
    Place,
    Region,
    WeatherObservation,
)


@dataclass(frozen=True)
class WeatherLocation:
    """A host-approved place and the region it belongs to."""

    place: Place
    region: Region

    def __post_init__(self) -> None:
        if self.place.region_id != self.region.region_id:
            raise ValueError("weather place and region do not match")


@dataclass(frozen=True)
class WeatherQuality:
    """Host-approved quality identity, source variable, and UCUM unit mapping."""

    quality_id: str
    name: str
    variable: str
    source_unit: str
    unit_code: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.quality_id,
                self.name,
                self.variable,
                self.source_unit,
                self.unit_code,
            )
        ):
            raise ValueError("invalid admitted weather quality")


def _validate_observations(
    rows: tuple[WeatherObservation, ...],
    location: WeatherLocation,
    quality: WeatherQuality | None,
) -> None:
    place = location.place
    if any(
        row.place_id != place.place_id
        or row.latitude != place.latitude
        or row.longitude != place.longitude
        for row in rows
    ):
        raise ValueError("weather source coordinates differ from admitted place")
    if quality is not None and any(
        row.variable != quality.variable or row.unit != quality.source_unit
        for row in rows
    ):
        raise ValueError("weather quality differs from admission")


def _located_records(
    rows: tuple[WeatherObservation, ...],
    location: WeatherLocation,
    quality: WeatherQuality | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    _validate_observations(rows, location, quality)
    place = location.place
    place_id = f"place:{place.place_id}"
    region_id = f"region:{location.region.region_id}"
    records = [
        dict(
            row.model_dump(mode="json", exclude_none=True),
            id=row.source_event_id,
            node_type="WeatherObservation",
        )
        for row in rows
    ]
    if quality is not None:
        for record in records:
            record["unit_code"] = quality.unit_code
        records.append(
            {
                "id": f"quality:{quality.quality_id}",
                "node_type": "QualityTerm",
                "name": quality.name,
            }
        )
    records.extend(
        [
            dict(place.model_dump(mode="json"), id=place_id, node_type="Place"),
            dict(
                location.region.model_dump(mode="json"),
                id=region_id,
                node_type="Region",
            ),
        ]
    )
    edges = [
        {
            "source": row.source_event_id,
            "target": place_id,
            "relationship": "occurredAt",
        }
        for row in rows
    ]
    if quality is not None:
        edges.extend(
            {
                "source": row.source_event_id,
                "target": f"quality:{quality.quality_id}",
                "relationship": "observedQuality",
            }
            for row in rows
        )
    edges.append({"source": place_id, "target": region_id, "relationship": "locatedIn"})
    return records, edges
