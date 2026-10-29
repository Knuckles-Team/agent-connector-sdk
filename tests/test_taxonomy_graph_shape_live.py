"""Real provider, MCP, source ingestion and graph SHACL taxonomy proof."""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import pytest
from fastmcp import FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from source_graph_helpers import (
    assert_shape_cycle,
    graph_shape_results,
    import_source_mapping,
    sync_failure_cycle,
)
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.manifest.model import (
    ResourceRelation,
    ResourceSpec,
    SchemaMapping,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.taxonomy.graph_stream import register_taxonomy_graph_stream
from agent_connector_sdk.taxonomy.provider import TaxonomyProvider
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse

pytestmark = pytest.mark.skipif(
    os.environ.get("EG_TEST_SOURCE_SHAPES") != "1",
    reason="requires the graph source datatype and shape projection candidate",
)


def _response(provider_name, identifier):
    if provider_name == "gbif":
        data = {
            "key": identifier,
            "nubKey": identifier,
            "rank": "GENUS" if identifier == 11 else "SPECIES",
            "scientificName": f"Taxon {identifier}",
            "parentKey": None if identifier == 11 else 11,
        }
    else:
        data = {
            "reports": [
                {
                    "taxonomy": {
                        "tax_id": identifier,
                        "rank": "GENUS" if identifier == 1 else "SPECIES",
                        "parents": [] if identifier == 1 else [1],
                        "current_scientific_name": {"name": f"Taxon {identifier}"},
                    }
                }
            ]
        }
    return json.dumps(data).encode()


async def _exercise(url, provider_name):
    engine = await scoped_client(["*"])
    try:
        mappings = {
            "Taxon": {
                "ontology_class": "Taxon",
                "fields": {
                    "scientific_name": "scientificName",
                    "term_curie": "termCurie",
                    "ncbi_taxon_id": "ncbiTaxonId",
                    "gbif_taxon_id": "gbifTaxonId",
                },
            },
            "TaxonRank": {"ontology_class": "TaxonRank", "fields": {"name": "name"}},
        }
        ontology = b"""@prefix : <http://knuckles.team/kg#> .
          @prefix owl: <http://www.w3.org/2002/07/owl#> .
          @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
          :parentTaxon a owl:ObjectProperty ; rdfs:domain :Taxon ; rdfs:range :Taxon .
          :taxonRank a owl:ObjectProperty ; rdfs:domain :Taxon ; rdfs:range :TaxonRank ."""
        context = await import_source_mapping(
            engine, CONNECTOR, mappings, ontology=ontology
        )

        async def authority(_connector):
            return _catalog(), context

        async def authorize(tenant, ctx):
            return tenant == "allowed" and ctx is not None

        @asynccontextmanager
        async def quota(_name):
            yield

        provider = TaxonomyProvider(
            provider=provider_name,
            http=HttpClientOptions(
                base_url=url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            max_bytes=65536,
        )
        server = FastMCP("taxonomy-graph-shape")
        identifiers = ["1", "2"] if provider_name == "ncbi" else ["11", "22"]
        prefix = "NCBITaxon" if provider_name == "ncbi" else "GBIF"
        register_taxonomy_graph_stream(
            server,
            provider,
            identifiers,
            tenant="allowed",
            name="taxa",
            connector=CONNECTOR,
            policy_revision="v1",
            authorize=authorize,
            max_records=2,
            crosswalk={
                f"{prefix}:{identifiers[0]}": ("1", "11"),
                f"{prefix}:{identifiers[1]}": ("2", "22"),
            },
            ranks={"GENUS": "genus", "SPECIES": "species"},
            roots=[f"{prefix}:{identifiers[0]}"],
        )
        preset = ToolPreset(
            name="taxa",
            server=CONNECTOR,
            tool="taxa",
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
        resources = [
            ResourceSpec(
                name="Taxon",
                relations=[
                    ResourceRelation(name="taxonRank", target="TaxonRank"),
                    ResourceRelation(name="parentTaxon", target="Taxon"),
                ],
            ),
            ResourceSpec(name="TaxonRank"),
        ]

        def adapter():
            return McpToolSourceAdapter(
                preset,
                connector=CONNECTOR,
                mapping_reference=f"connector:{CONNECTOR}",
                schema_mappings={
                    "Taxon": SchemaMapping(ontology_class="Taxon"),
                    "TaxonRank": SchemaMapping(ontology_class="TaxonRank"),
                },
                resources=resources,
            )

        sink = EpistemicGraphSink(engine, authority)
        cycle = await sync_failure_cycle(
            server, sink, CONNECTOR, "taxa", "taxa", adapter, repeat=True
        )
        valid, invalid, edges = await graph_shape_results(engine, "Taxon")
        return cycle, valid, invalid, edges
    finally:
        await engine.close()


@pytest.mark.parametrize("provider_name", ["ncbi", "gbif"])
def test_taxonomy_source_to_graph_shape_and_replay(live_ingest, provider_name):  # noqa: F811
    first_id, second_id = (1, 2) if provider_name == "ncbi" else (11, 22)
    scripted = [
        ScriptedResponse(body=_response(provider_name, first_id)),
        ScriptedResponse(body=_response(provider_name, second_id)),
        ScriptedResponse(status=503),
        ScriptedResponse(body=_response(provider_name, first_id)),
        ScriptedResponse(body=_response(provider_name, second_id)),
        ScriptedResponse(body=_response(provider_name, first_id)),
        ScriptedResponse(body=_response(provider_name, second_id)),
    ]
    with ScriptedHttpServer(*scripted) as server:
        cycle, valid, invalid, edges = asyncio.run_coroutine_threadsafe(
            _exercise(server.base_url, provider_name), live_ingest._loop
        ).result(60)
    assert_shape_cycle(cycle, valid, invalid)
    assert len(edges) == 3
    assert {row["r"]["relationship"] for row in edges} == {"parentTaxon", "taxonRank"}
    taxon_nodes = {row["a"]["termCurie"]: row["a"] for row in edges}
    assert {
        (row["ncbiTaxonId"], row["gbifTaxonId"]) for row in taxon_nodes.values()
    } == {("1", "11"), ("2", "22")}
