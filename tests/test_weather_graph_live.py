import asyncio
import json
from contextlib import asynccontextmanager

import pytest
import source_graph_helpers as graph_helpers
from fastmcp import FastMCP
from live_engine import PRINCIPAL, TENANT, live_ingest, scoped_client  # noqa: F401
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR
from weather_test_helpers import weather_provider, weather_request

from agent_connector_sdk.earth_observations.weather_stream import (
    register_weather_stream,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


async def exercise(url, provider_name):
    engine = await scoped_client(["*"])
    try:
        context = await graph_helpers.import_source_mapping(
            engine,
            CONNECTOR,
            {
                "WeatherObservation": {
                    "fields": {
                        "latitude": "latitude",
                        "longitude": "longitude",
                        "place_id": "placeId",
                        "unit": "unit",
                        "value": "value",
                        "variable": "variable",
                    },
                    "ontology_class": "WeatherObservation",
                }
            },
        )

        async def authority(_connector):
            return _catalog(), context

        @asynccontextmanager
        async def quota(name):
            yield

        async def authorize(tenant, ctx):
            return tenant == "allowed" and ctx is not None

        provider = weather_provider(url, provider_name, quota, lambda code: code == "1")
        request = weather_request(tenant="allowed", hours=2, max_records=2)
        server = FastMCP("weather-graph")
        register_weather_stream(
            server,
            provider,
            request,
            authorize=authorize,
            policy_revision="v1",
            name="weather",
            connector=CONNECTOR,
        )
        preset = ToolPreset(
            name="weather",
            server=CONNECTOR,
            tool="weather",
            id_field="id",
            records_path="records",
            params_style="args",
            params={"mode": "delta"},
            updated_since_param="state",
            checkpoint_path="checkpoint",
        )

        def adapter():
            return graph_helpers.source_adapter(
                preset, CONNECTOR, f"connector:{CONNECTOR}#mappings/WeatherObservation"
            )

        sink = EpistemicGraphSink(engine, authority)
        first, before, failed, repeated, _ = await graph_helpers.sync_failure_cycle(
            server, sink, CONNECTOR, "weather", "weather", adapter
        )
        rows = await engine.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        return first, before, failed, repeated, rows
    finally:
        await engine.close()


@pytest.mark.parametrize("provider_name", ["open_meteo", "noaa_hourly"])
def test_weather_graph_failure_and_repeat(live_ingest, provider_name):  # noqa: F811
    if provider_name == "open_meteo":
        body = {
            "utc_offset_seconds": 0,
            "latitude": 45.1,
            "longitude": -92.1,
            "hourly_units": {"temperature_2m": "°C"},
            "hourly": {
                "time": ["2025-01-01T00:00", "2025-01-01T01:00"],
                "temperature_2m": [1.1, 2.2],
            },
        }
    else:
        body = [
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
        ]
    response = json.dumps(body).encode()
    with ScriptedHttpServer(
        ScriptedResponse(body=response),
        ScriptedResponse(status=503),
        ScriptedResponse(body=response),
    ) as server:
        first, before, failed, repeated, rows = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url, provider_name), live_ingest._loop
        ).result(30)
        assert first.accepted == 2
        assert before.accepted_checkpoint == failed.accepted_checkpoint
        assert repeated.accepted == 2
        nodes = [row["n"] for row in rows if row["n"].get("source_stream") == "weather"]
        assert len(nodes) == 2, nodes
        assert {node["value"] for node in nodes} == {1.1, 2.2}
        assert {node["latitude"] for node in nodes} == {45.1}
