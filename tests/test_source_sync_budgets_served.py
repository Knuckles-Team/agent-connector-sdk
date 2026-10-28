"""Deadline refusal over served MCP with real graph-backed progress."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401
from test_source_sync_served import _ClientSession

from agent_connector_sdk.ingest.source_sync import (
    KvSourceCheckpoints,
    SourceSyncRunner,
    SyncBudget,
)
from agent_connector_sdk.ingest.sources import IngestSourceSpec


async def _exercise(ingest):
    server = FastMCP("source-budget")

    @server.tool(annotations={"readOnlyHint": True})
    async def slow_page():
        await asyncio.sleep(10)
        return {"data": [{"id": "never"}]}

    spec = IngestSourceSpec(
        source_id="items",
        record_type="FixtureItem",
        tools=("slow_page",),
        records_path="data",
        id_field="id",
    )
    engine = await scoped_client(
        [
            "kv:read",
            "kv:write",
            "kv:shared:read",
            "kv:shared:write",
            "query:cypher",
            "node:read",
        ]
    )
    try:
        async with Client(server) as client:
            runner = SourceSyncRunner(
                connector="budget-fixture",
                server="budget-fixture",
                session=_ClientSession(client),
                ingest=ingest,
                checkpoints=KvSourceCheckpoints(engine),
                budget=SyncBudget(max_seconds=0.05),
            )
            report = await runner.sync(spec)
            state = await runner.status("items")
        rows = await engine.query.cypher_read("MATCH (n) RETURN n LIMIT 10")
        return report, state, rows
    finally:
        await engine.close()


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.53")
def test_served_timeout_keeps_graph_progress(live_ingest):  # noqa: F811
    report, state, rows = asyncio.run_coroutine_threadsafe(
        _exercise(live_ingest), live_ingest._loop
    ).result(30)
    assert report.state == "partial" and report.reason == "deadline_exceeded"
    assert report.submitted == 0 and state.cursor is None and state.digests == {}
    assert rows == []
