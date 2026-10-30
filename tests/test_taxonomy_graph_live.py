import json
from contextlib import asynccontextmanager

import pytest
import source_graph_helpers as graph_helpers
from fastmcp import FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR

from scion_sdk.adapters.mcp_tool import McpToolSourceAdapter
from scion_sdk.http.options import HttpClientOptions
from scion_sdk.http.retry import RetryPolicy
from scion_sdk.sinks.epistemic_graph import EpistemicGraphSink
from scion_sdk.taxonomy.provider import TaxonomyProvider
from scion_sdk.taxonomy.stream import register_taxonomy_stream


async def exercise(url, provider_name):
    engine = await scoped_client(["*"])
    try:
        context = await graph_helpers.import_source_mapping(
            engine,
            CONNECTOR,
            {
                "Taxon": {
                    "fields": {
                        "parent_term_curie": "parentTermCurie",
                        "scientific_name": "scientificName",
                        "taxon_rank": "rankLabel",
                        "term_curie": "termCurie",
                    },
                    "ontology_class": "Taxon",
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
        server = FastMCP("taxonomy-graph")
        register_taxonomy_stream(
            server,
            provider,
            ["1", "2"],
            tenant="allowed",
            batch_size=1,
            authorize=authorize,
            name="taxa",
            connector=CONNECTOR,
        )
        preset = graph_helpers.paged_preset(CONNECTOR, "taxa")

        def adapter():
            return McpToolSourceAdapter(
                preset,
                connector=CONNECTOR,
                mapping_reference=f"connector:{CONNECTOR}#mappings/Taxon",
            )

        sink = EpistemicGraphSink(engine, authority)
        return await graph_helpers.collect_source_cycle(
            engine, server, sink, CONNECTOR, "taxa", adapter
        )
    finally:
        await engine.close()


@pytest.mark.parametrize("provider_name", ["ncbi", "gbif"])
def test_taxonomy_source_graph_checkpoint_restart(live_ingest, provider_name):  # noqa: F811
    def body(identifier):
        if provider_name == "gbif":
            data = {
                "key": identifier,
                "nubKey": identifier,
                "scientificName": f"Taxon {identifier}",
                "rank": "SPECIES",
                "parentKey": 9,
            }
        else:
            data = {
                "reports": [
                    {
                        "taxonomy": {
                            "tax_id": identifier,
                            "rank": "SPECIES",
                            "parents": [9],
                            "current_scientific_name": {"name": f"Taxon {identifier}"},
                        }
                    }
                ]
            }
        return json.dumps(data).encode()

    nodes = graph_helpers.scripted_page_cycle(
        exercise, body, provider_name, live_ingest._loop
    )
    prefix = "GBIF" if provider_name == "gbif" else "NCBITaxon"
    assert {node["termCurie"] for node in nodes} == {f"{prefix}:1", f"{prefix}:2"}
    assert {node["scientificName"] for node in nodes} == {"Taxon 1", "Taxon 2"}
    assert {node["parentTermCurie"] for node in nodes} == {f"{prefix}:9"}
    assert {node["rankLabel"] for node in nodes} == {"SPECIES"}
