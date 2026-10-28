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
