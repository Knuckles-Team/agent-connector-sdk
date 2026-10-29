import asyncio
import json
import os

import pytest
import source_graph_helpers as graph_helpers
from fastmcp import FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from test_event_feeds import CONNECTOR

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.earth_observations.occurrence import OccurrenceProvider
from agent_connector_sdk.earth_observations.occurrence_context import OccurrenceContext
from agent_connector_sdk.earth_observations.records import Place, Region
from agent_connector_sdk.earth_observations.stream import register_occurrence_stream
from agent_connector_sdk.manifest.model import (
    ResourceRelation,
    ResourceSpec,
    SchemaMapping,
)
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.taxonomy.records import TaxonRecord
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


async def exercise(url, provider_name, with_context=False):
    engine = await scoped_client(["*"])
    try:
        mappings = {
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
        }
        ontology = None
        if with_context:
            mappings["OrganismObservation"]["fields"]["event_time_utc"] = (
                "observationTime"
            )
            mappings["OrganismObservation"]["datatypes"] = {
                "event_time_utc": "xsd:dateTime"
            }
            mappings.update(
                {
                    "Taxon": {
                        "ontology_class": "Taxon",
                        "fields": {
                            "scientific_name": "scientificName",
                            "term_curie": "termCurie",
                        },
                    },
                    "Place": {"ontology_class": "Place", "fields": {"name": "name"}},
                    "Region": {"ontology_class": "Region", "fields": {"name": "name"}},
                }
            )
            ontology = b"@prefix : <http://knuckles.team/kg#> . @prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . :observedTaxon a owl:ObjectProperty ; rdfs:domain :OrganismObservation ; rdfs:range :Taxon . :occurredAt a owl:ObjectProperty ; rdfs:domain :OrganismObservation ; rdfs:range :Place . :locatedIn a owl:ObjectProperty ; rdfs:domain :Place ; rdfs:range :Region ."
        authority, authorize, quota = await graph_helpers.admitted_source_fixture(
            engine, CONNECTOR, mappings, ontology=ontology
        )

        provider = OccurrenceProvider(
            provider=provider_name,
            http=graph_helpers.loopback_options(url),
            quota=quota,
            max_bytes=65536,
            license_admitted=lambda tag: tag == "CC-BY",
        )
        server = FastMCP("taxonomy-graph")
        approved = None
        if with_context:
            region = Region(region_id="region", name="Region", kind="operator")
            places = {
                f"{provider_name}:occurrence:{identifier}:location": Place(
                    place_id=f"{provider_name}:occurrence:{identifier}:location",
                    name=f"Site {identifier}",
                    region_id="region",
                    latitude=45.0,
                    longitude=-92.0,
                )
                for identifier in ("1", "2")
            }
            source_taxon = "GBIF:7" if provider_name == "gbif" else "iNaturalist:7"
            approved = OccurrenceContext(
                taxa={
                    source_taxon: TaxonRecord(
                        scientific_name="Taxon",
                        term_curie="NCBITaxon:123",
                        ncbi_taxon_id="123",
                        gbif_taxon_id="7",
                    )
                },
                places=places,
                regions={"region": region},
            )
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
            context=approved,
        )
        preset = graph_helpers.paged_preset(CONNECTOR, "taxa")

        def adapter():
            if not with_context:
                return graph_helpers.source_adapter(
                    preset,
                    CONNECTOR,
                    f"connector:{CONNECTOR}#mappings/OrganismObservation",
                )
            typed = preset.model_copy(
                update={
                    "record_mode": "typed_entities",
                    "node_type_field": "node_type",
                    "relationships_path": "relationships",
                }
            )
            resources = [
                ResourceSpec(
                    name="OrganismObservation",
                    relations=[
                        ResourceRelation(name="observedTaxon", target="Taxon"),
                        ResourceRelation(name="occurredAt", target="Place"),
                    ],
                ),
                ResourceSpec(name="Taxon"),
                ResourceSpec(
                    name="Place",
                    relations=[ResourceRelation(name="locatedIn", target="Region")],
                ),
                ResourceSpec(name="Region"),
            ]
            return McpToolSourceAdapter(
                typed,
                connector=CONNECTOR,
                mapping_reference=f"connector:{CONNECTOR}",
                schema_mappings={
                    key: SchemaMapping(ontology_class=key) for key in mappings
                },
                resources=resources,
            )

        sink = EpistemicGraphSink(engine, authority)
        cycle = await graph_helpers.collect_source_cycle(
            engine, server, sink, CONNECTOR, "taxa", adapter
        )
        if not with_context:
            return cycle
        valid, invalid, edges = await graph_helpers.graph_shape_results(
            engine, "OrganismObservation"
        )
        return cycle, valid, invalid, edges
    finally:
        await engine.close()


def _body(provider_name, identifier):
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


@pytest.mark.parametrize("provider_name", ["gbif", "inaturalist"])
def test_occurrence_source_graph_checkpoint_restart(live_ingest, provider_name):  # noqa: F811

    nodes = graph_helpers.scripted_page_cycle(
        exercise,
        lambda identifier: _body(provider_name, identifier),
        provider_name,
        live_ingest._loop,
    )
    expected_taxon = "GBIF:7" if provider_name == "gbif" else "iNaturalist:7"
    assert {node["sourceTaxonId"] for node in nodes} == {expected_taxon}
    assert {node["scientificName"] for node in nodes} == {"Taxon"}
    assert {node["latitude"] for node in nodes} == {45.0}
    assert {node["longitude"] for node in nodes} == {-92.0}


def _wrong_location(provider_name):
    data = json.loads(_body(provider_name, 2))
    if provider_name == "gbif":
        data["decimalLatitude"] = 46.0
    else:
        data["results"][0]["location"] = "46,-92"
    return json.dumps(data).encode()


@pytest.mark.parametrize("provider_name", ["gbif", "inaturalist"])
def test_occurrence_context_source_shape_and_replay(live_ingest, provider_name):  # noqa: F811
    if os.environ.get("EG_TEST_SOURCE_SHAPES") != "1":
        pytest.skip("requires the graph source datatype and shape projection candidate")
    scripted = [
        ScriptedResponse(body=_body(provider_name, 1)),
        ScriptedResponse(body=_wrong_location(provider_name)),
        ScriptedResponse(body=_body(provider_name, 2)),
        ScriptedResponse(body=_body(provider_name, 1)),
    ]
    with ScriptedHttpServer(*scripted) as http:
        cycle, valid, invalid, edges = asyncio.run_coroutine_threadsafe(
            exercise(http.base_url, provider_name, True), live_ingest._loop
        ).result(60)
    graph_helpers.assert_shape_cycle(cycle, valid, invalid)
    assert len(edges) == 6
    assert {row["r"]["relationship"] for row in edges} == {
        "observedTaxon",
        "occurredAt",
        "locatedIn",
    }
