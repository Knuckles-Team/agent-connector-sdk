"""Bounded Open-Meteo and NOAA hourly temperature observations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from agent_connector_sdk.earth_observations.records import WeatherObservation
from agent_connector_sdk.http.client import create_async_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.taxonomy.provider import _bounded

WeatherProviderName = Literal["open_meteo", "noaa_hourly"]


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


class WeatherProvider:
    """Read hourly temperatures using explicit host and source policy."""

    def __init__(
        self,
        *,
        provider: WeatherProviderName,
        http: HttpClientOptions,
        quota: Callable[[str], AbstractAsyncContextManager[Any]],
        max_bytes: int,
        quality_admitted: Callable[[str], bool],
    ) -> None:
        if (
            provider not in ("open_meteo", "noaa_hourly")
            or not http.pin_egress
            or http.retry.max_attempts != 1
            or max_bytes < 1
        ):
            raise ValueError("invalid weather provider policy")
        self.provider = provider
        self.http = http
        self.quota = quota
        self.max_bytes = max_bytes
        self.quality_admitted = quality_admitted

    async def read(self, request: WeatherRequest) -> tuple[WeatherObservation, ...]:
        if (
            not request.tenant
            or not request.source
            or not request.place_id
            or not request.license_tag
            or request.start.utcoffset() is None
            or request.end.utcoffset() is None
            or request.start >= request.end
            or not 1 <= request.max_records <= 10000
        ):
            raise ValueError("invalid weather request")
        path, params = _request(self.provider, request)
        try:
            async with (
                self.quota(self.provider),
                create_async_http_client(self.http) as client,
                client.stream("GET", path, params=params) as response,
            ):
                response.raise_for_status()
                payload = await _bounded(response.aiter_bytes(), self.max_bytes)
            data = json.loads(payload)
            digest = hashlib.sha256(payload).hexdigest()
            pairs = _read_rows(self.provider, data, request, self.quality_admitted)
            return tuple(
                _observation(
                    self.provider,
                    request,
                    digest,
                    timestamp,
                    value,
                    unit,
                    latitude,
                    longitude,
                )
                for timestamp, value, unit, latitude, longitude in pairs
            )
        except Exception:
            raise WeatherProviderError("weather provider response refused") from None


def _request(
    provider: WeatherProviderName, request: WeatherRequest
) -> tuple[str, dict[str, str]]:
    start = request.start.astimezone(UTC).isoformat()
    end = request.end.astimezone(UTC).isoformat()
    if provider == "noaa_hourly":
        if (
            not request.station
            or not request.station.isascii()
            or not request.station.isalnum()
        ):
            raise ValueError("NOAA station required")
        return "data/v1", {
            "dataset": "global-hourly",
            "stations": request.station,
            "startDate": start,
            "endDate": end,
            "format": "json",
        }
    if (
        request.latitude is None
        or request.longitude is None
        or not -90 <= request.latitude <= 90
        or not -180 <= request.longitude <= 180
    ):
        raise ValueError("Open-Meteo coordinates required")
    return "v1/archive", {
        "latitude": str(request.latitude),
        "longitude": str(request.longitude),
        "start_date": request.start.astimezone(UTC).date().isoformat(),
        "end_date": request.end.astimezone(UTC).date().isoformat(),
        "hourly": "temperature_2m",
        "timezone": "UTC",
    }


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("invalid hourly observation time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=UTC)
        if parsed.utcoffset() is None
        else parsed.astimezone(UTC)
    )


def _read_rows(
    provider: WeatherProviderName,
    data: Any,
    request: WeatherRequest,
    quality_admitted: Callable[[str], bool],
) -> list[tuple[datetime, float, str, float, float]]:
    if provider == "noaa_hourly":
        if not isinstance(data, list):
            raise ValueError("invalid NOAA response")
        values = []
        for item in data:
            if item["STATION"] != request.station:
                raise ValueError("NOAA station mismatch")
            value, quality = item["TMP"].split(",", 1)
            if value in ("+9999", "9999") or not quality_admitted(quality):
                raise ValueError("unadmitted NOAA value")
            values.append(
                (
                    _time(item["DATE"]),
                    int(value) / 10,
                    "°C",
                    float(item["LATITUDE"]),
                    float(item["LONGITUDE"]),
                )
            )
    else:
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
        values = [
            (_time(timestamp), float(value), unit, latitude, longitude)
            for timestamp, value in zip(times, temperatures, strict=True)
        ]
    selected = [item for item in values if request.start <= item[0] < request.end]
    if len(selected) > request.max_records or len(
        {item[0] for item in selected}
    ) != len(selected):
        raise ValueError("weather record bound or identity invalid")
    return selected


def _observation(
    provider: WeatherProviderName,
    request: WeatherRequest,
    digest: str,
    timestamp: datetime,
    value: float,
    unit: str,
    latitude: float,
    longitude: float,
) -> WeatherObservation:
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
