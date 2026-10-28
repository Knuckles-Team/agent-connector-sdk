"""Unpaged snapshots can be re-imported against the durable graph checkpoint."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from test_contracts_and_sink import _catalog
from test_event_feeds import CONNECTOR
from test_event_replay_checkpoint import _import_mapping

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.transports.mcp import McpTransport


async def _exercise():
    client = await scoped_client(["*"])
    try:
        context = await _import_mapping(client)

        async def authority(_connector):
            return _catalog(), context

        state = [{"id": "account-1", "balance": 9}]
        server = FastMCP("account-fixture")

        @server.tool()
        def snapshot() -> list[dict[str, object]]:
            return list(state)

        preset = ToolPreset(
            name="account",
            server=CONNECTOR,
            tool="snapshot",
            id_field="id",
            params_style="args",
        )
        adapter = McpToolSourceAdapter(
            preset,
            connector=CONNECTOR,
            mapping_reference=f"connector:{CONNECTOR}#mappings/Event",
        )
        target = SyncTarget(
            CONNECTOR, EpistemicGraphSink(client, authority), max_pages=1
        )
        async with McpTransport().session(
            TransportEndpoint(in_process=server)
        ) as session:
            first = await sync_stream(session, adapter, target)
            repeat = await sync_stream(session, adapter, target)
            state[0]["balance"] = 10
            changed = await sync_stream(session, adapter, target)
        rows = await client.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        accounts = [
            row["n"] for row in rows if row["n"].get("source_stream") == "account"
        ]
        assert first.checkpoint != repeat.checkpoint != changed.checkpoint
        assert [account["source_record_id"] for account in accounts] == ["account-1"]
    finally:
        await client.close()


def test_snapshot_reimport_uses_durable_graph_checkpoint(live_ingest):  # noqa: F811
    asyncio.run_coroutine_threadsafe(_exercise(), live_ingest._loop).result(30)
