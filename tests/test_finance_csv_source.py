"""CSV statements pass through a served source and graph ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace

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
from test_finance_csv_import import _CONTEXT, _CSV, _MAPPING

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.finance.csv_import import AmbiguousCurrencyError
from agent_connector_sdk.finance.csv_source import (
    csv_activity_preset,
    register_csv_activity_tool,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.transports.mcp import McpTransport


def _server(content, context):
    server = FastMCP("csv-activity")
    register_csv_activity_tool(
        server,
        name="csv_activities",
        content=content,
        mapping=_MAPPING,
        context=context,
    )
    return server


def test_source_refuses_invalid_currency_before_registration():
    with pytest.raises(AmbiguousCurrencyError):
        _server(_CSV.replace(b",USD,", b",bad,"), _CONTEXT)


async def _import_mapping(client):
    context = _mutation_context().model_copy(update={"tenant_id": TENANT})
    key = "csv-activity-test:bind"
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
                    "Activity": {
                        "ontology_class": "Document",
                        "fields": {
                            "account_id": "xsd:string",
                            "source_event_id": "xsd:string",
                            "quantity": "xsd:double",
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
        producer=PackProducer(name="csv-test", version="1"),
        catalog=_catalog(),
        context=context,
    )
    assert result.result == "imported", result
    return context


async def _exercise():
    client = await scoped_client(["*"])
    try:
        context = await _import_mapping(client)

        async def authority(_connector):
            return _catalog(), context

        sink = EpistemicGraphSink(client, authority)
        preset = csv_activity_preset(
            stream="activities", server=CONNECTOR, tool="csv_activities"
        )
        adapter = McpToolSourceAdapter(
            preset,
            connector=CONNECTOR,
            mapping_reference=f"connector:{CONNECTOR}#mappings/Activity",
        )
        target = SyncTarget(CONNECTOR, sink, max_pages=1)

        async def run(content, account):
            server = _server(
                content, replace(_CONTEXT, account_id=account, tenant_id=TENANT)
            )
            async with McpTransport().session(
                TransportEndpoint(in_process=server)
            ) as session:
                return await sync_stream(session, adapter, target)

        first = await run(_CSV, "account-1")
        repeated = await run(_CSV, "account-1")
        second_account = await run(_CSV, "account-2")
        changed = await run(_CSV.replace(b"100.5", b"100.6"), "account-1")
        rows = await client.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        activities = [
            row["n"] for row in rows if row["n"].get("source_stream") == "activities"
        ]
        ids = [activity["source_record_id"] for activity in activities]
        assert len(ids) == len(set(ids)) == 6
        assert {activity["account_id"] for activity in activities} == {
            "account-1",
            "account-2",
        }
        assert sorted(activity["quantity"] for activity in activities) == [
            5,
            5,
            5,
            10,
            10,
            10,
        ]
        assert all(activity["source_event_id"] for activity in activities)
        assert all(
            result.accepted == 2
            for result in (first, repeated, second_account, changed)
        )
        assert (
            first.checkpoint
            != repeated.checkpoint
            != second_account.checkpoint
            != changed.checkpoint
        )
    finally:
        await client.close()


def test_real_graph_csv_reimport_preserves_activity_identity(live_ingest):  # noqa: F811
    asyncio.run_coroutine_threadsafe(_exercise(), live_ingest._loop).result(30)
