import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from fastmcp import FastMCP
from live_engine import PRINCIPAL, TENANT, live_ingest, scoped_client  # noqa: F401
from source_graph_helpers import import_source_mapping, sync_failure_cycle
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.taxonomy.provider import TaxonomyProvider
from agent_connector_sdk.taxonomy.stream import register_taxonomy_stream
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


async def exercise(url, provider_name):
    engine = await scoped_client(["*"])
    try:
        context = await import_source_mapping(
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
        preset = ToolPreset(
            name="taxa",
            server=CONNECTOR,
            tool="taxa",
            id_field="id",
            records_path="records",
            params_style="args",
            params={"mode": "delta"},
            pagination="cursor",
            cursor_param="cursor",
            cursor_path="next",
            updated_since_param="state",
            checkpoint_path="checkpoint",
        )

        def adapter():
            return McpToolSourceAdapter(
                preset,
                connector=CONNECTOR,
                mapping_reference=f"connector:{CONNECTOR}#mappings/Taxon",
            )

        sink = EpistemicGraphSink(engine, authority)
        first, before, failed, second, third = await sync_failure_cycle(
            server, sink, CONNECTOR, "taxa", "taxa", adapter, repeat=True
        )
        rows = await engine.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        return first, before, failed, second, third, rows
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

    with ScriptedHttpServer(
        ScriptedResponse(body=body(1)),
        ScriptedResponse(status=503),
        ScriptedResponse(body=body(2)),
        ScriptedResponse(body=body(1)),
    ) as server:
        first, before, failed, second, third, rows = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url, provider_name), live_ingest._loop
        ).result(30)
        assert first.accepted == 1
        assert before.accepted_checkpoint == failed.accepted_checkpoint
        assert second.accepted == 1
        assert third.accepted == 1
        nodes = [row["n"] for row in rows if row["n"].get("source_stream") == "taxa"]
        assert len(nodes) == 2, nodes
        prefix = "GBIF" if provider_name == "gbif" else "NCBITaxon"
        assert {node["termCurie"] for node in nodes} == {f"{prefix}:1", f"{prefix}:2"}
        assert {node["scientificName"] for node in nodes} == {"Taxon 1", "Taxon 2"}
        assert {node["parentTermCurie"] for node in nodes} == {f"{prefix}:9"}
        assert {node["rankLabel"] for node in nodes} == {"SPECIES"}
