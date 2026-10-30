"""Parse bounded NOAA hourly temperature observations."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from scion_sdk.earth_observations._weather_daily import _WeatherRow


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("invalid hourly observation time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=UTC)
        if parsed.utcoffset() is None
        else parsed.astimezone(UTC)
    )


def _noaa_rows(
    data: Any, station: str | None, quality_admitted: Callable[[str], bool]
) -> list[_WeatherRow]:
    if not isinstance(data, list):
        raise ValueError("invalid NOAA response")
    return [_noaa_row(item, station, quality_admitted) for item in data]


def _noaa_row(
    item: Any, station: str | None, quality_admitted: Callable[[str], bool]
) -> _WeatherRow:
    if item["STATION"] != station:
        raise ValueError("NOAA station mismatch")
    value, quality = item["TMP"].split(",", 1)
    if value in ("+9999", "9999") or not quality_admitted(quality):
        raise ValueError("unadmitted NOAA value")
    return _WeatherRow(
        _time(item["DATE"]),
        int(value) / 10,
        "°C",
        float(item["LATITUDE"]),
        float(item["LONGITUDE"]),
    )
