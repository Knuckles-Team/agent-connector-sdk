"""Host-approved weather locations survive real graph ingest and replay."""

import asyncio
import json
import os

import pytest
from fastmcp import FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from source_graph_helpers import admitted_source_fixture, sync_failure_cycle
from test_event_feeds import CONNECTOR
from weather_test_helpers import weather_provider, weather_request

from scion_sdk.adapters.mcp_tool import McpToolSourceAdapter
from scion_sdk.earth_observations.records import Place, Region
from scion_sdk.earth_observations.weather_location import (
    WeatherLocation,
    WeatherQuality,
)
from scion_sdk.earth_observations.weather_stream import (
    register_weather_stream,
)
from scion_sdk.manifest.model import (
    ResourceRelation,
    ResourceSpec,
    SchemaMapping,
)
from scion_sdk.manifest.presets import ToolPreset
from scion_sdk.sinks.epistemic_graph import EpistemicGraphSink
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


async def exercise(url, with_quality):
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
        if with_quality:
            mappings["WeatherObservation"] = {
                "ontology_class": "WeatherObservation",
                "fields": {
                    "value": "quantityValue",
                    "event_time_utc": "observationTime",
                    "unit_code": "unitCode",
                },
                "datatypes": {"value": "xsd:decimal", "event_time_utc": "xsd:dateTime"},
            }
            mappings["QualityTerm"] = {
                "ontology_class": "QualityTerm",
                "fields": {"name": "name"},
            }
        ontology = b"@prefix : <http://knuckles.team/kg#> . @prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . :occurredAt a owl:ObjectProperty ; rdfs:domain :WeatherObservation ; rdfs:range :Place . :locatedIn a owl:ObjectProperty ; rdfs:domain :Place ; rdfs:range :Region ."
        if with_quality:
            ontology += b" :observedQuality a owl:ObjectProperty ; rdfs:domain :WeatherObservation ; rdfs:range :QualityTerm ."
        authority, authorize, quota = await admitted_source_fixture(
            engine, CONNECTOR, mappings, ontology=ontology
        )

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
            quality=WeatherQuality(
                quality_id="air-temperature",
                name="Air temperature",
                variable="temperature",
                source_unit="°C",
                unit_code="Cel",
            )
            if with_quality
            else None,
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

        if with_quality:
            resources[0].relations.append(
                ResourceRelation(name="observedQuality", target="QualityTerm")
            )
            resources.append(ResourceSpec(name="QualityTerm"))

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
        shapes = None
        if with_quality:
            query = (
                "MATCH (:WeatherObservation) |> VALIDATE SHAPE "
                "<http://knuckles.team/kg#WeatherObservationShape> PROJECT 'http://knuckles.team/kg#'"
            )
            shapes = (
                await engine.query.uql(query + " KEEP CONFORMING"),
                await engine.query.uql(query + " KEEP VIOLATING"),
            )
        return first, before, failed, repeated, edges, shapes
    finally:
        await engine.close()


@pytest.mark.parametrize("with_quality", [False, True])
def test_located_weather_refusal_and_repeat(live_ingest, with_quality):  # noqa: F811
    if with_quality and os.environ.get("EG_TEST_SOURCE_SHAPES") != "1":
        pytest.skip("requires the graph source datatype and shape projection candidate")

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
        first, before, failed, repeated, edges, shapes = (
            asyncio.run_coroutine_threadsafe(
                exercise(server.base_url, with_quality), live_ingest._loop
            ).result(30)
        )
    assert first.accepted == (10 if with_quality else 7)
    assert before.accepted_checkpoint == failed.accepted_checkpoint
    assert repeated.accepted == (10 if with_quality else 7)
    assert len(edges) == (5 if with_quality else 3), edges
    if with_quality:
        valid, invalid = shapes
        assert len(valid["rows"]) == 2
        assert invalid["rows"] == []
        assert [row["r"]["relationship"] for row in edges].count("observedQuality") == 2
    assert [row["r"]["relationship"] for row in edges].count("occurredAt") == 2
    assert [row["r"]["relationship"] for row in edges].count("locatedIn") == 1
    assert {
        row["b"]["name"] for row in edges if row["r"]["relationship"] == "locatedIn"
    } == {"Region"}
