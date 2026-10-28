import json
from contextlib import asynccontextmanager

import pytest
import source_graph_helpers as graph_helpers
from fastmcp import FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR

from agent_connector_sdk.earth_observations.occurrence import OccurrenceProvider
from agent_connector_sdk.earth_observations.stream import register_occurrence_stream
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink


async def exercise(url, provider_name):
    engine = await scoped_client(["*"])
    try:
        context = await graph_helpers.import_source_mapping(
            engine,
            CONNECTOR,
            {
                "OrganismObservation": {
                    "fields": {
                        "latitude": "latitude",
                        "longitude": "longitude",
                        "place_id": "sourcePlaceId",
                        "scientific_name": "scientificName",
                        "taxon_id": "sourceTaxonId",
                    },
                    "ontology_class": "OrganismObservation",
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

        provider = OccurrenceProvider(
            provider=provider_name,
            http=graph_helpers.loopback_options(url),
            quota=quota,
            max_bytes=65536,
            license_admitted=lambda tag: tag == "CC-BY",
        )
        server = FastMCP("taxonomy-graph")
        register_occurrence_stream(
            server,
            provider,
            ["1", "2"],
            tenant="allowed",
            batch_size=1,
            policy_revision="v1",
            authorize=authorize,
            name="taxa",
            connector=CONNECTOR,
        )
        preset = graph_helpers.paged_preset(CONNECTOR, "taxa")

        def adapter():
            return graph_helpers.source_adapter(
                preset, CONNECTOR, f"connector:{CONNECTOR}#mappings/OrganismObservation"
            )

        sink = EpistemicGraphSink(engine, authority)
        return await graph_helpers.collect_source_cycle(
            engine, server, sink, CONNECTOR, "taxa", adapter
        )
    finally:
        await engine.close()


@pytest.mark.parametrize("provider_name", ["gbif", "inaturalist"])
def test_occurrence_source_graph_checkpoint_restart(live_ingest, provider_name):  # noqa: F811
    def body(identifier):
        if provider_name == "gbif":
            data = {
                "key": identifier,
                "taxonKey": 7,
                "scientificName": "Taxon",
                "eventDate": "2026-01-02T03:04:00Z",
                "license": "CC-BY",
                "decimalLatitude": 45.0,
                "decimalLongitude": -92.0,
                "basisOfRecord": "HUMAN_OBSERVATION",
            }
        else:
            data = {
                "results": [
                    {
                        "id": identifier,
                        "taxon": {"id": 7, "name": "Taxon"},
                        "time_observed_at": "2026-01-02T03:04:00Z",
                        "license_code": "CC-BY",
                        "location": "45,-92",
                    }
                ]
            }
        return json.dumps(data).encode()

    nodes = graph_helpers.scripted_page_cycle(
        exercise, body, provider_name, live_ingest._loop
    )
    expected_taxon = "GBIF:7" if provider_name == "gbif" else "iNaturalist:7"
    assert {node["sourceTaxonId"] for node in nodes} == {expected_taxon}
    assert {node["scientificName"] for node in nodes} == {"Taxon"}
    assert {node["latitude"] for node in nodes} == {45.0}
    assert {node["longitude"] for node in nodes} == {-92.0}
