import asyncio
import gzip
from pathlib import Path

from fastmcp import FastMCP
from live_engine import PRINCIPAL, TENANT, live_ingest, scoped_client  # noqa: F401
from source_graph_helpers import import_source_mapping, sync_failure_cycle
from storm_test_helpers import archive_policy
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.earth_observations.storm import (
    NoaaStormArchive,
    StormAdmission,
)
from agent_connector_sdk.earth_observations.storm_stream import register_storm_stream
from agent_connector_sdk.manifest.model import (
    ResourceRelation,
    ResourceSpec,
    SchemaMapping,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink


async def exercise(root: Path, compressed: bytes):
    engine = await scoped_client(["*"])
    try:
        context = await import_source_mapping(
            engine,
            CONNECTOR,
            {
                "WeatherEvent": {
                    "fields": {
                        "event_type": "eventType",
                        "weather_system_id": "systemId",
                    },
                    "ontology_class": "WeatherEvent",
                },
                "WeatherSystem": {
                    "fields": {"name": "name"},
                    "ontology_class": "WeatherSystem",
                },
            },
            ontology=b"@prefix : <http://knuckles.team/kg#> . @prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . :occursIn a owl:ObjectProperty ; rdfs:domain :WeatherEvent ; rdfs:range :WeatherSystem .",
        )

        async def authority(_connector):
            return _catalog(), context

        async def authorize(tenant, ctx):
            return tenant == "allowed" and ctx is not None

        policy = archive_policy(root, compressed)
        archive = NoaaStormArchive(
            policy,
            lambda row: StormAdmission(
                f"noaa:{row['EPISODE_ID']}",
                f"Episode {row['EPISODE_ID']}",
                "place",
                "EF1",
            ),
        )
        server = FastMCP("storm-graph")
        register_storm_stream(
            server,
            archive,
            ["33", "34"],
            tenant="allowed",
            name="storm",
            connector=CONNECTOR,
            batch_size=1,
            policy_revision="v1",
            authorize=authorize,
        )
        preset = ToolPreset(
            name="storm",
            server=CONNECTOR,
            tool="storm",
            id_field="id",
            records_path="records",
            params_style="args",
            params={"mode": "delta"},
            record_mode="typed_entities",
            node_type_field="node_type",
            relationships_path="relationships",
            pagination="cursor",
            cursor_param="cursor",
            cursor_path="next",
            updated_since_param="state",
            checkpoint_path="checkpoint",
        )
        mappings = {
            "WeatherEvent": SchemaMapping(ontology_class="WeatherEvent"),
            "WeatherSystem": SchemaMapping(ontology_class="WeatherSystem"),
        }
        resources = [
            ResourceSpec(
                name="WeatherEvent",
                relations=[ResourceRelation(name="occursIn", target="WeatherSystem")],
            ),
            ResourceSpec(name="WeatherSystem"),
        ]

        def adapter():
            return McpToolSourceAdapter(
                preset,
                connector=CONNECTOR,
                mapping_reference=f"connector:{CONNECTOR}",
                schema_mappings=mappings,
                resources=resources,
            )

        sink = EpistemicGraphSink(engine, authority)
        path = root / "source.csv.gz"
        first, before, failed, second, repeated = await sync_failure_cycle(
            server,
            sink,
            CONNECTOR,
            "storm",
            "storm",
            adapter,
            repeat=True,
            fault=lambda: path.write_bytes(b"wrong"),
            recover=lambda: path.write_bytes(compressed),
        )
        rows = await engine.query.cypher_read(
            "MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 100"
        )
        return first, before, failed, second, repeated, rows
    finally:
        await engine.close()


def test_storm_event_to_approved_weather_system(live_ingest, tmp_path):  # noqa: F811
    body = b"BEGIN_YEARMONTH,BEGIN_DAY,BEGIN_TIME,EPISODE_ID,EVENT_ID,CZ_TIMEZONE,EVENT_TYPE\n202503,1,1630,22,33,CST-6,Tornado\n202503,1,1700,22,34,CST-6,Tornado\n"
    compressed = gzip.compress(body)
    (tmp_path / "source.csv.gz").write_bytes(compressed)
    first, before, failed, second, repeated, rows = asyncio.run_coroutine_threadsafe(
        exercise(tmp_path, compressed), live_ingest._loop
    ).result(30)
    assert first.accepted == 3
    assert before.accepted_checkpoint == failed.accepted_checkpoint
    assert second.accepted == 3
    assert repeated.accepted == 3
    assert len(rows) == 2, rows
    assert {row["r"]["relationship"] for row in rows} == {"occursIn"}
    assert {row["a"]["type"] for row in rows} == {"WeatherEvent"}
    assert {row["b"]["type"] for row in rows} == {"WeatherSystem"}
    assert {row["b"]["name"] for row in rows} == {"Episode 22"}
    assert len({row["b"]["id"] for row in rows}) == 1
