"""Import fixture source mappings into the real graph for integration tests."""

import hashlib
import json

from epistemic_graph.connector_pack import (
    ConnectorPackArchiveBuilder,
    ConnectorPackClient,
    ConnectorPackEntryContent,
)
from epistemic_graph.generated.connector_pack import PackEntryKind, PackProducer
from live_engine import PRINCIPAL, TENANT
from test_contracts_and_sink import _catalog, _mutation_context


async def import_source_mapping(client, connector, mappings, *, ontology=None):
    context = _mutation_context().model_copy(update={"tenant_id": TENANT})
    key = "source-fixture:bind"
    await client._send(
        "ConnectorPack",
        {
            "op": {
                "op": "bind",
                "request": {
                    "context": context.model_copy(
                        update={"idempotency_key": key}
                    ).model_dump(mode="json"),
                    "connector": connector,
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
        uri=f"mcp-server://{connector}",
        name=connector,
        media_type="application/json",
        body=json.dumps({"name": connector}).encode(),
    )
    resource = ConnectorPackEntryContent(
        kind=PackEntryKind.RESOURCE,
        uri="connector://resources",
        name="connector-resources",
        media_type="application/json",
        body=json.dumps(
            {"connector": connector, "sources": [], "schema_mappings": mappings}
        ).encode(),
        output_schema=b'{"type":"object"}',
    )
    entries = [resource]
    if ontology is not None:
        entries.append(
            ConnectorPackEntryContent(
                kind=PackEntryKind.ONTOLOGY,
                uri="ontology://fixture",
                name="fixture",
                media_type="text/turtle",
                body=ontology,
            )
        )
    result = await ConnectorPackClient(client).import_pack(
        ConnectorPackArchiveBuilder.build(server, entries),
        connector=connector,
        server_package_version="1.0.0",
        producer=PackProducer(name="source-fixture", version="1"),
        catalog=_catalog(),
        context=context,
    )
    assert result.result == "imported"
    return context


def assert_shape_cycle(cycle, valid, invalid):
    """Verify replay, rejection and both sides of shape validation."""
    first, before, failed, second, replay = cycle[:5]
    assert first.accepted == second.accepted == replay.accepted == 7
    assert before.accepted_checkpoint == failed.accepted_checkpoint
    assert len(valid["rows"]) == 2
    assert invalid["rows"] == []


async def sync_failure_cycle(
    server,
    sink,
    connector,
    stream,
    tool,
    adapter,
    *,
    repeat=False,
    fault=None,
    recover=None,
):
    """Run one accepted page, one refusal, resume, and optionally replay."""
    import pytest

    from agent_connector_sdk.ports.errors import McpTransportError
    from agent_connector_sdk.ports.session import TransportEndpoint
    from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
    from agent_connector_sdk.transports.mcp import McpTransport

    target = SyncTarget(connector, sink, max_pages=1)
    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        first = await sync_stream(session, adapter(), target)
        before = await sink.source_status(connector, stream)
        if fault is not None:
            fault()
        with pytest.raises(McpTransportError, match=tool):
            await sync_stream(session, adapter(), target)
        failed = await sink.source_status(connector, stream)
        if recover is not None:
            recover()
        second = await sync_stream(session, adapter(), target)
        replayed = await sync_stream(session, adapter(), target) if repeat else None
    return first, before, failed, second, replayed


def loopback_options(url):
    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.http.retry import RetryPolicy

    return HttpClientOptions(
        base_url=url,
        pin_egress=True,
        allow_loopback=True,
        retry=RetryPolicy(max_attempts=1),
    )


def source_adapter(preset, connector, mapping_reference):
    from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter

    return McpToolSourceAdapter(
        preset,
        connector=connector,
        mapping_reference=mapping_reference,
    )


async def collect_source_cycle(engine, server, sink, connector, stream, adapter):
    cycle = await sync_failure_cycle(
        server, sink, connector, stream, stream, adapter, repeat=True
    )
    rows = await engine.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
    return (*cycle, rows)


def paged_preset(connector, name):
    from agent_connector_sdk.manifest.presets import ToolPreset

    return ToolPreset(
        name=name,
        server=connector,
        tool=name,
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


def scripted_page_cycle(exercise, body, provider, loop):
    import asyncio

    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )

    with ScriptedHttpServer(
        ScriptedResponse(body=body(1)),
        ScriptedResponse(status=503),
        ScriptedResponse(body=body(2)),
        ScriptedResponse(body=body(1)),
    ) as server:
        first, before, failed, second, third, rows = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url, provider), loop
        ).result(30)
    assert first.accepted == second.accepted == third.accepted == 1
    assert before.accepted_checkpoint == failed.accepted_checkpoint
    nodes = [row["n"] for row in rows if row["n"].get("source_stream") == "taxa"]
    assert len(nodes) == 2, nodes
    return nodes


async def graph_shape_results(engine, node_type):
    """Read conforming and violating nodes plus source relationships."""
    query = (
        f"MATCH (:{node_type}) |> VALIDATE SHAPE "
        f"<http://knuckles.team/kg#{node_type}Shape> PROJECT 'http://knuckles.team/kg#'"
    )
    valid = await engine.query.uql(query + " KEEP CONFORMING")
    invalid = await engine.query.uql(query + " KEEP VIOLATING")
    edges = await engine.query.cypher_read(
        "MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 100"
    )
    return valid, invalid, edges


async def admitted_source_fixture(engine, connector, mappings, *, ontology=None):
    """Bind a fixture pack and provide the shared authorization and quota."""
    from contextlib import asynccontextmanager

    context = await import_source_mapping(
        engine, connector, mappings, ontology=ontology
    )

    async def authority(_connector):
        return _catalog(), context

    async def authorize(tenant, ctx):
        return tenant == "allowed" and ctx is not None

    @asynccontextmanager
    async def quota(_name):
        yield

    return authority, authorize, quota
