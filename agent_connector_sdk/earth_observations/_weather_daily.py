"""Interpret NOAA daily observed temperatures only with host time authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

TimeAuthority = Callable[[str, str, str], datetime]
WeatherRow = tuple[datetime, float, str, float, float]


def _daily_rows(
    data: Any,
    station: str,
    *,
    quality_admitted: Callable[[str], bool],
    time_authority: TimeAuthority,
) -> list[WeatherRow]:
    if not isinstance(data, list):
        raise ValueError("invalid NOAA daily response")
    return [
        _daily_row(
            item,
            station,
            quality_admitted=quality_admitted,
            time_authority=time_authority,
        )
        for item in data
    ]


def _daily_row(
    item: Any,
    station: str,
    *,
    quality_admitted: Callable[[str], bool],
    time_authority: TimeAuthority,
) -> WeatherRow:
    if item["STATION"] != station:
        raise ValueError("NOAA station mismatch")
    attributes = item["TOBS_ATTRIBUTES"].split(",")
    if len(attributes) != 4 or not quality_admitted(attributes[1]):
        raise ValueError("unadmitted NOAA daily quality")
    clock = _clock(attributes[3])
    day = item["DATE"]
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError("invalid NOAA observation date")
    timestamp = time_authority(station, day, clock)
    if timestamp.utcoffset() is None:
        raise ValueError("host did not resolve observation timezone")
    return (
        timestamp.astimezone(UTC),
        float(item["TOBS"]),
        "°C",
        float(item["LATITUDE"]),
        float(item["LONGITUDE"]),
    )


def _clock(value: str) -> str:
    if len(value) != 4 or not value.isascii() or not value.isdecimal():
        raise ValueError("NOAA observation time missing")
    if int(value[:2]) > 23 or int(value[2:]) > 59:
        raise ValueError("NOAA observation time invalid")
    return value
