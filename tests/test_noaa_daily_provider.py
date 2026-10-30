"""Daily station temperatures require observed time and host time authority."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone

import pytest
from weather_test_helpers import weather_request

from scion_sdk.earth_observations.weather import (
    WeatherProvider,
    WeatherProviderError,
)
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.http.retry import RetryPolicy
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.asyncio
async def test_daily_temperature_uses_admitted_station_time():
    @asynccontextmanager
    async def quota(name):
        yield

    def station_time(station, day, clock):
        assert (station, day, clock) == ("USC00110072", "2025-01-01", "0630")
        return datetime(2025, 1, 1, 6, 30, tzinfo=timezone(timedelta(hours=-6)))

    body = [
        {
            "STATION": "USC00110072",
            "DATE": "2025-01-01",
            "TOBS": "-2.8",
            "TOBS_ATTRIBUTES": ",,7,0630",
            "LATITUDE": "41.20693",
            "LONGITUDE": "-90.74187",
        }
    ]
    with ScriptedHttpServer(ScriptedResponse(body=json.dumps(body).encode())) as server:
        source = WeatherProvider(
            provider="noaa_daily",
            http=HttpClientOptions(
                base_url=server.base_url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            max_bytes=65536,
            quality_admitted=lambda quality: quality == "",
            time_authority=station_time,
        )
        request = weather_request(hours=24, max_records=1, station="USC00110072")
        (record,) = await source.read(request)
        assert record.event_time_utc == datetime(2025, 1, 1, 12, 30, tzinfo=UTC)
        assert record.value == -2.8
        assert (record.latitude, record.longitude) == (41.20693, -90.74187)
        assert "dataset=daily-summaries" in server.requests[0].path


@pytest.mark.asyncio
async def test_daily_without_source_time_fails_closed():
    @asynccontextmanager
    async def quota(name):
        yield

    body = [{"STATION": "123", "DATE": "2025-01-01", "TMAX": "3.5"}]
    with ScriptedHttpServer(ScriptedResponse(body=json.dumps(body).encode())) as server:
        options = HttpClientOptions(
            base_url=server.base_url,
            pin_egress=True,
            allow_loopback=True,
            retry=RetryPolicy(max_attempts=1),
        )
        with pytest.raises(ValueError, match="policy"):
            WeatherProvider(
                provider="noaa_daily",
                http=options,
                quota=quota,
                max_bytes=65536,
                quality_admitted=lambda quality: True,
            )
        source = WeatherProvider(
            provider="noaa_daily",
            http=options,
            quota=quota,
            max_bytes=65536,
            quality_admitted=lambda quality: True,
            time_authority=lambda station, day, clock: datetime.now(UTC),
        )
        request = weather_request(hours=24, max_records=1, station="123")
        with pytest.raises(WeatherProviderError):
            await source.read(request)
