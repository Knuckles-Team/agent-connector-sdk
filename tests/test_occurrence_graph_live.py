import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import pytest
from epistemic_graph.connector_pack import (
    ConnectorPackArchiveBuilder,
    ConnectorPackClient,
    ConnectorPackEntryContent,
)
from epistemic_graph.generated.connector_pack import PackEntryKind, PackProducer
from fastmcp import FastMCP
from live_engine import PRINCIPAL, TENANT, live_ingest, scoped_client  # noqa: F401
from test_contracts_and_sink import _catalog, _mutation_context
from test_event_feeds import CONNECTOR

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.earth_observations.occurrence import OccurrenceProvider
from agent_connector_sdk.earth_observations.stream import register_occurrence_stream
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import McpTransportError
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse
from agent_connector_sdk.transports.mcp import McpTransport


async def _strict_mapping(client):
    context = _mutation_context().model_copy(update={"tenant_id": TENANT})
    key = "occurrence-graph-test:bind"
    await client._send(
        "ConnectorPack",
        {
            "op": {
                "op": "bind",
                "request": {
                    "context": context.model_copy(
                        update={"idempotency_key": key}
                    ).model_dump(mode="json"),
                    "connector": CONNECTOR,
                    "importer": "principal:sha256:"
                    + hashlib.sha256(PRINCIPAL.encode()).hexdigest(),
                },
            }
        },
        None,
        idempotency_key=key,
    )
    server = ConnectorPackEntryContent(
        kind=PackEntryKind.MCP_SERVER,
        uri=f"mcp-server://{CONNECTOR}",
        name=CONNECTOR,
        media_type="application/json",
        body=json.dumps({"name": CONNECTOR}).encode(),
    )
    resource = ConnectorPackEntryContent(
        kind=PackEntryKind.RESOURCE,
        uri="connector://resources",
        name="connector-resources",
        media_type="application/json",
        body=json.dumps(
            {
                "connector": CONNECTOR,
                "sources": [],
                "schema_mappings": {
                    "OrganismObservation": {
                        "ontology_class": "OrganismObservation",
                        "fields": {
                            "scientific_name": "scientificName",
                            "taxon_id": "sourceTaxonId",
                            "place_id": "sourcePlaceId",
                            "latitude": "latitude",
                            "longitude": "longitude",
                        },
                    }
                },
            }
        ).encode(),
        output_schema=b'{"type":"object"}',
    )
    result = await ConnectorPackClient(client).import_pack(
        ConnectorPackArchiveBuilder.build(server, [resource]),
        connector=CONNECTOR,
        server_package_version="1.0.0",
        producer=PackProducer(name="occurrence-graph-test", version="1"),
        catalog=_catalog(),
        context=context,
    )
    assert result.result == "imported"
    return context


async def exercise(url, provider_name):
    engine = await scoped_client(["*"])
    try:
        context = await _strict_mapping(engine)

        async def authority(_connector):
            return _catalog(), context

        @asynccontextmanager
        async def quota(name):
            yield

        async def authorize(tenant, ctx):
            return tenant == "allowed" and ctx is not None

        provider = OccurrenceProvider(
            provider=provider_name,
            http=HttpClientOptions(
                base_url=url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
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
                mapping_reference=f"connector:{CONNECTOR}#mappings/OrganismObservation",
            )

        sink = EpistemicGraphSink(engine, authority)
        target = SyncTarget(CONNECTOR, sink, max_pages=1)
        async with McpTransport().session(
            TransportEndpoint(in_process=server)
        ) as session:
            first = await sync_stream(session, adapter(), target)
            before = await sink.source_status(CONNECTOR, "taxa")
            with pytest.raises(McpTransportError, match="taxa"):
                await sync_stream(session, adapter(), target)
            failed = await sink.source_status(CONNECTOR, "taxa")
            second = await sync_stream(session, adapter(), target)
            third = await sync_stream(session, adapter(), target)
        rows = await engine.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        return first, before, failed, second, third, rows
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
        expected_taxon = "GBIF:7" if provider_name == "gbif" else "iNaturalist:7"
        assert {node["sourceTaxonId"] for node in nodes} == {expected_taxon}
        assert {node["scientificName"] for node in nodes} == {"Taxon"}
        assert {node["latitude"] for node in nodes} == {45.0}
        assert {node["longitude"] for node in nodes} == {-92.0}
