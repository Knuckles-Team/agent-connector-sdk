"""Bounded weather provider fixtures shared by served and direct tests."""

from datetime import UTC, datetime, timedelta

from source_graph_helpers import loopback_options

from scion_sdk.earth_observations.weather import (
    WeatherProvider,
    WeatherRequest,
)


def weather_provider(
    url, provider, quota, quality=lambda code: code == "1", time_authority=None
):
    return WeatherProvider(
        provider=provider,
        http=loopback_options(url),
        quota=quota,
        max_bytes=65536,
        quality_admitted=quality,
        time_authority=time_authority,
    )


def weather_request(tenant="tenant", hours=2, max_records=2, station="123"):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return WeatherRequest(
        tenant=tenant,
        source="weather",
        place_id="place",
        license_tag="admitted",
        start=start,
        end=start + timedelta(hours=hours),
        max_records=max_records,
        latitude=45,
        longitude=-92,
        station=station,
    )
