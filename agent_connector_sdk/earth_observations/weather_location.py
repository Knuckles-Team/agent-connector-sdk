"""Host-admitted place and region records for weather streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.earth_observations.records import (
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


def _located_records(
    rows: tuple[WeatherObservation, ...], location: WeatherLocation
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    place = location.place
    if any(
        row.place_id != place.place_id
        or row.latitude != place.latitude
        or row.longitude != place.longitude
        for row in rows
    ):
        raise ValueError("weather source coordinates differ from admitted place")
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
    edges.append({"source": place_id, "target": region_id, "relationship": "locatedIn"})
    return records, edges
