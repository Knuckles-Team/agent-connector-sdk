"""Bounded Open-Meteo and NOAA hourly temperature observations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from scion_sdk.earth_observations._weather_daily import (
    TimeAuthority,
    _daily_rows,
    _WeatherRow,
)
from scion_sdk.earth_observations._weather_hourly import _noaa_rows, _time
from scion_sdk.earth_observations.records import WeatherObservation
from scion_sdk.http._bounded_provider import _bounded, _BoundedProvider
from scion_sdk.http.client import create_async_http_client
from scion_sdk.http.options import HttpClientOptions

WeatherProviderName = Literal["open_meteo", "noaa_hourly", "noaa_daily"]


class WeatherProviderError(RuntimeError):
    """A bounded weather source request could not be accepted."""


@dataclass(frozen=True)
class WeatherRequest:
    tenant: str
    source: str
    place_id: str
    license_tag: str
    start: datetime
    end: datetime
    max_records: int
    latitude: float | None = None
    longitude: float | None = None
    station: str | None = None


class WeatherProvider(_BoundedProvider[WeatherProviderName]):
    """Read hourly temperatures using explicit host and source policy."""

    def __init__(
        self,
        *,
        provider: WeatherProviderName,
        http: HttpClientOptions,
        quota: Callable[[str], AbstractAsyncContextManager[Any]],
        max_bytes: int,
        quality_admitted: Callable[[str], bool],
        time_authority: TimeAuthority | None = None,
    ) -> None:
        if provider not in ("open_meteo", "noaa_hourly", "noaa_daily") or (
            provider == "noaa_daily" and time_authority is None
        ):
            raise ValueError("invalid weather provider policy")
        super().__init__(provider=provider, http=http, quota=quota, max_bytes=max_bytes)
        self.quality_admitted = quality_admitted
        self.time_authority = time_authority

    async def read(self, request: WeatherRequest) -> tuple[WeatherObservation, ...]:
        _validate_request(request)
        try:
            return await self._read_page(request)
        except Exception:
            raise WeatherProviderError("weather provider response refused") from None

    async def _read_page(
        self, request: WeatherRequest
    ) -> tuple[WeatherObservation, ...]:
        path, params = _request(self.provider, request)
        async with (
            self.quota(self.provider),
            create_async_http_client(self.http) as client,
            client.stream("GET", path, params=params) as response,
        ):
            response.raise_for_status()
            payload = await _bounded(response.aiter_bytes(), self.max_bytes)
        rows = _read_rows(
            self.provider,
            json.loads(payload),
            request=request,
            quality_admitted=self.quality_admitted,
            time_authority=self.time_authority,
        )
        digest = hashlib.sha256(payload).hexdigest()
        return tuple(
            _observation(self.provider, request, digest=digest, row=row) for row in rows
        )


def _validate_request(request: WeatherRequest) -> None:
    if (
        not request.tenant
        or not request.source
        or not request.place_id
        or not request.license_tag
    ):
        raise ValueError("invalid weather request identity")
    if request.start.utcoffset() is None or request.end.utcoffset() is None:
        raise ValueError("weather request needs timezone-aware bounds")
    if request.start >= request.end or not 1 <= request.max_records <= 10000:
        raise ValueError("invalid weather request limits")


def _request(
    provider: WeatherProviderName, request: WeatherRequest
) -> tuple[str, dict[str, str]]:
    if provider in ("noaa_hourly", "noaa_daily"):
        return _noaa_request(provider, request)
    return _meteo_request(request)


def _noaa_request(
    provider: WeatherProviderName, request: WeatherRequest
) -> tuple[str, dict[str, str]]:
    if (
        not request.station
        or not request.station.isascii()
        or not request.station.isalnum()
    ):
        raise ValueError("NOAA station required")
    if provider == "noaa_daily":
        start = (request.start.astimezone(UTC).date() - timedelta(days=1)).isoformat()
        end = (request.end.astimezone(UTC).date() + timedelta(days=1)).isoformat()
        return "data/v1", {
            "dataset": "daily-summaries",
            "stations": request.station,
            "startDate": start,
            "endDate": end,
            "format": "json",
            "includeAttributes": "true",
            "includeStationLocation": "true",
            "units": "metric",
        }
    return "data/v1", {
        "dataset": "global-hourly",
        "stations": request.station,
        "startDate": request.start.astimezone(UTC).isoformat(),
        "endDate": request.end.astimezone(UTC).isoformat(),
        "format": "json",
    }


def _meteo_request(request: WeatherRequest) -> tuple[str, dict[str, str]]:
    if request.latitude is None or request.longitude is None:
        raise ValueError("Open-Meteo coordinates required")
    if not -90 <= request.latitude <= 90 or not -180 <= request.longitude <= 180:
        raise ValueError("Open-Meteo coordinates invalid")
    return "v1/archive", {
        "latitude": str(request.latitude),
        "longitude": str(request.longitude),
        "start_date": request.start.astimezone(UTC).date().isoformat(),
        "end_date": request.end.astimezone(UTC).date().isoformat(),
        "hourly": "temperature_2m",
        "timezone": "UTC",
    }


def _read_rows(
    provider: WeatherProviderName,
    data: Any,
    *,
    request: WeatherRequest,
    quality_admitted: Callable[[str], bool],
    time_authority: TimeAuthority | None,
) -> list[_WeatherRow]:
    if provider == "noaa_daily":
        if request.station is None or time_authority is None:
            raise ValueError("NOAA time authority missing")
        values = _daily_rows(
            data,
            request.station,
            quality_admitted=quality_admitted,
            time_authority=time_authority,
        )
    elif provider == "noaa_hourly":
        values = _noaa_rows(data, request.station, quality_admitted)
    else:
        values = _meteo_rows(data)
    selected = [item for item in values if request.start <= item[0] < request.end]
    if len(selected) > request.max_records or len(
        {item[0] for item in selected}
    ) != len(selected):
        raise ValueError("weather record bound or identity invalid")
    return selected


def _meteo_rows(data: Any) -> list[_WeatherRow]:
    if not isinstance(data, dict) or data.get("utc_offset_seconds") != 0:
        raise ValueError("Open-Meteo response not UTC")
    hourly = data["hourly"]
    times, temperatures = hourly["time"], hourly["temperature_2m"]
    if (
        not isinstance(times, list)
        or not isinstance(temperatures, list)
        or len(times) != len(temperatures)
    ):
        raise ValueError("invalid Open-Meteo series")
    unit = data["hourly_units"]["temperature_2m"]
    if not isinstance(unit, str) or not unit:
        raise ValueError("Open-Meteo unit missing")
    latitude, longitude = float(data["latitude"]), float(data["longitude"])
    return [
        _WeatherRow(_time(timestamp), float(value), unit, latitude, longitude)
        for timestamp, value in zip(times, temperatures, strict=True)
    ]


def _observation(
    provider: WeatherProviderName,
    request: WeatherRequest,
    *,
    digest: str,
    row: _WeatherRow,
) -> WeatherObservation:
    timestamp, value, unit, latitude, longitude = row
    if not math.isfinite(value):
        raise ValueError("nonfinite weather value")
    identity = hashlib.sha256(
        json.dumps(
            [provider, request.place_id, timestamp.isoformat(), "temperature"],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return WeatherObservation(
        tenant_id=request.tenant,
        source_id=request.source,
        provider=provider,
        source_event_id=identity,
        event_time_utc=timestamp,
        observed_at_utc=datetime.now(UTC),
        license_tag=request.license_tag,
        source_digest=digest,
        place_id=request.place_id,
        variable="temperature",
        value=value,
        unit=unit,
        latitude=latitude,
        longitude=longitude,
    )
