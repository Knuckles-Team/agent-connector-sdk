import json
from contextlib import asynccontextmanager

import pytest
from weather_test_helpers import weather_provider, weather_request

from agent_connector_sdk.earth_observations.weather import (
    WeatherProviderError,
)
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.asyncio
@pytest.mark.spec("SCION-SOURCE-INGEST-R008")
@pytest.mark.parametrize(
    ("provider", "body", "unit", "expected"),
    [
        (
            "open_meteo",
            {
                "utc_offset_seconds": 0,
                "latitude": 45.1,
                "longitude": -92.1,
                "hourly_units": {"temperature_2m": "°C"},
                "hourly": {
                    "time": ["2025-01-01T00:00", "2025-01-01T01:00"],
                    "temperature_2m": [1.1, 2.2],
                },
            },
            "°C",
            [1.1, 2.2],
        ),
        (
            "noaa_hourly",
            [
                {
                    "STATION": "123",
                    "DATE": "2025-01-01T00:00:00",
                    "TMP": "+0011,1",
                    "LATITUDE": "45.1",
                    "LONGITUDE": "-92.1",
                },
                {
                    "STATION": "123",
                    "DATE": "2025-01-01T01:00:00",
                    "TMP": "+0022,1",
                    "LATITUDE": "45.1",
                    "LONGITUDE": "-92.1",
                },
            ],
            "°C",
            [1.1, 2.2],
        ),
    ],
)
async def test_hourly_sources_preserve_units_and_grid_coordinates(
    provider, body, unit, expected
):
    @asynccontextmanager
    async def quota(name):
        yield

    with ScriptedHttpServer(ScriptedResponse(body=json.dumps(body).encode())) as server:
        source = weather_provider(
            server.base_url, provider, quota, lambda code: code == "1"
        )
        request = weather_request(tenant="tenant", hours=2, max_records=2)
        rows = await source.read(request)
        assert [row.value for row in rows] == expected
        assert all(
            row.unit == unit and row.latitude == 45.1 and row.longitude == -92.1
            for row in rows
        )
        assert len({row.source_event_id for row in rows}) == 2


@pytest.mark.spec("SCION-SOURCE-INGEST-R008")
@pytest.mark.asyncio
async def test_noaa_missing_or_unapproved_values_fail():
    @asynccontextmanager
    async def quota(name):
        yield

    body = [
        {
            "STATION": "123",
            "DATE": "2025-01-01T00:00:00",
            "TMP": "+9999,9",
            "LATITUDE": "45",
            "LONGITUDE": "-92",
        }
    ]
    with ScriptedHttpServer(ScriptedResponse(body=json.dumps(body).encode())) as server:
        source = weather_provider(
            server.base_url, "noaa_hourly", quota, lambda code: code == "1"
        )
        request = weather_request(tenant="tenant", hours=24, max_records=24)
        with pytest.raises(WeatherProviderError):
            await source.read(request)
