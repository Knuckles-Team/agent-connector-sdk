"""Host-approved weather locations survive real graph ingest and replay."""

import asyncio
import json
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from source_graph_helpers import import_source_mapping, sync_failure_cycle
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR
from weather_test_helpers import weather_provider, weather_request

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.earth_observations.records import Place, Region
from agent_connector_sdk.earth_observations.weather_location import WeatherLocation
from agent_connector_sdk.earth_observations.weather_stream import (
    register_weather_stream,
)
from agent_connector_sdk.manifest.model import (
    ResourceRelation,
    ResourceSpec,
    SchemaMapping,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


async def exercise(url):
    engine = await scoped_client(["*"])
    try:
        mappings = {
            "WeatherObservation": {
                "ontology_class": "WeatherObservation",
                "fields": {"value": "value"},
            },
            "Place": {"ontology_class": "Place", "fields": {"name": "name"}},
            "Region": {"ontology_class": "Region", "fields": {"name": "name"}},
        }
        ontology = b"@prefix : <http://knuckles.team/kg#> . @prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . :occurredAt a owl:ObjectProperty ; rdfs:domain :WeatherObservation ; rdfs:range :Place . :locatedIn a owl:ObjectProperty ; rdfs:domain :Place ; rdfs:range :Region ."
        context = await import_source_mapping(
            engine, CONNECTOR, mappings, ontology=ontology
        )

        async def authority(_connector):
            return _catalog(), context

        @asynccontextmanager
        async def quota(name):
            yield

        async def authorize(tenant, ctx):
            return tenant == "allowed" and ctx is not None

        provider = weather_provider(url, "noaa_hourly", quota)
        request = weather_request(tenant="allowed", hours=2, max_records=2)
        region = Region(region_id="approved-region", name="Region", kind="operator")
        place = Place(
            place_id="place",
            name="Station",
            region_id=region.region_id,
            latitude=45.1,
            longitude=-92.1,
        )
        server = FastMCP("weather-locations")
        register_weather_stream(
            server,
            provider,
            request,
            authorize=authorize,
            policy_revision="v1",
            name="weather",
            connector=CONNECTOR,
            location=WeatherLocation(place, region),
        )
        preset = ToolPreset(
            name="weather",
            server=CONNECTOR,
            tool="weather",
            id_field="id",
            records_path="records",
            params_style="args",
            params={"mode": "delta"},
            record_mode="typed_entities",
            node_type_field="node_type",
            relationships_path="relationships",
            updated_since_param="state",
            checkpoint_path="checkpoint",
        )
        declared = {key: SchemaMapping(ontology_class=key) for key in mappings}
        resources = [
            ResourceSpec(
                name="WeatherObservation",
                relations=[ResourceRelation(name="occurredAt", target="Place")],
            ),
            ResourceSpec(
                name="Place",
                relations=[ResourceRelation(name="locatedIn", target="Region")],
            ),
            ResourceSpec(name="Region"),
        ]

        def adapter():
            return McpToolSourceAdapter(
                preset,
                connector=CONNECTOR,
                mapping_reference=f"connector:{CONNECTOR}",
                schema_mappings=declared,
                resources=resources,
            )

        sink = EpistemicGraphSink(engine, authority)
        first, before, failed, repeated, _ = await sync_failure_cycle(
            server, sink, CONNECTOR, "weather", "weather", adapter
        )
        edges = await engine.query.cypher_read(
            "MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 100"
        )
        return first, before, failed, repeated, edges
    finally:
        await engine.close()


def test_located_weather_refusal_and_repeat(live_ingest):  # noqa: F811
    def body(latitude):
        rows = [
            {
                "STATION": "123",
                "DATE": f"2025-01-01T0{hour}:00:00",
                "TMP": "+0011,1",
                "LATITUDE": str(latitude),
                "LONGITUDE": "-92.1",
            }
            for hour in (0, 1)
        ]
        return json.dumps(rows).encode()

    with ScriptedHttpServer(
        ScriptedResponse(body=body(45.1)),
        ScriptedResponse(body=body(46.0)),
        ScriptedResponse(body=body(45.1)),
    ) as server:
        first, before, failed, repeated, edges = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url), live_ingest._loop
        ).result(30)
    assert first.accepted == 7
    assert before.accepted_checkpoint == failed.accepted_checkpoint
    assert repeated.accepted == 7
    assert len(edges) == 3, edges
    assert [row["r"]["relationship"] for row in edges].count("occurredAt") == 2
    assert [row["r"]["relationship"] for row in edges].count("locatedIn") == 1
    assert {
        row["b"]["name"] for row in edges if row["r"]["relationship"] == "locatedIn"
    } == {"Region"}
