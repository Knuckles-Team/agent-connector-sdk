"""The source sync runner against a real engine (SCION-SOURCE-INGEST-R004.24).

A fixture connector serves the declared ``fixture_list_items`` tool in process.
The runner calls it through a real MCP client session, submits to the real
engine ``SourceIngest`` method, keeps its checkpoint in real shared-scope KV,
and the engine's governed refusal of an unmapped record type is observed:
no node is written and no record digest advances.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401 - pytest fixture

from agent_connector_sdk.ingest.service import KnowledgeIngest
from agent_connector_sdk.ingest.source_sync import (
    KvSourceCheckpoints,
    SourceSyncRunner,
)
from agent_connector_sdk.ingest.sources import IngestSourceSpec

ITEMS = [{"id": f"item-{i}", "name": f"Item {i}", "rank": i} for i in range(1, 4)]
SPEC = IngestSourceSpec(
    source_id="items",
    record_type="FixtureItem",
    tools=("fixture_list_items",),
    records_path="data",
    id_field="id",
    title_field="name",
)


def _fixture_connector() -> FastMCP:
    mcp = FastMCP("fixture-mcp")

    @mcp.tool(annotations={"readOnlyHint": True})
    def fixture_list_items() -> dict[str, Any]:
        """List the fixture items."""
        return {"data": ITEMS}

    return mcp


class _ClientSession:
    """An SDK source session over a real MCP client."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def tool_is_read_only(self, name: str) -> bool:
        tools = {tool.name: tool for tool in await self._client.list_tools()}
        annotations = tools[name].annotations
        return bool(annotations and annotations.read_only_hint)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        result = await self._client.call_tool(name, dict(arguments))
        return result.structured_content or json.loads(result.content[0].text)


async def _run(ingest: KnowledgeIngest) -> tuple[Any, Any, list[dict[str, Any]], Any]:
    engine = await scoped_client(
        [
            "kv:read",
            "kv:write",
            "kv:shared:read",
            "kv:shared:write",
            "node:read",
            "query:cypher",
            "query:unified",
        ]
    )
    async with Client(_fixture_connector()) as client:
        runner = SourceSyncRunner(
            connector="fixture-mcp",
            server="fixture-mcp",
            session=_ClientSession(client),
            ingest=ingest,
            checkpoints=KvSourceCheckpoints(engine),
        )
        first = await runner.sync(SPEC, job_id="job-1")
        second = await runner.sync(SPEC, job_id="job-2")
        state = await runner.status("items")
    try:
        rows = await engine.query.cypher_read("MATCH (n:FixtureItem) RETURN n LIMIT 10")
    finally:
        await engine.close()
    return first, second, rows, state


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.24")
def test_sync_runner_against_real_engine(
    live_ingest: KnowledgeIngest,  # noqa: F811 - pytest fixture
) -> None:
    loop = live_ingest._loop  # type: ignore[attr-defined]
    first, second, rows, state = asyncio.run_coroutine_threadsafe(
        _run(live_ingest), loop
    ).result(120)
    # The engine admits source records only under an imported connector pack
    # mapping (connector:<connector>#mappings/<record type>). This
    # fixture connector imported none, so the engine refuses the batch.
    assert first.state == "failed" and first.reason == "ingest_refused", first
    assert first.engine_code == "UNKNOWN_MAPPING_REFERENCE", first
    assert first.submitted == 0 and first.records_seen == 3
    assert second.state == "failed" and second.unchanged == 0, second
    assert rows == [], rows
    assert state.state == "failed" and state.digests == {}, state
    assert state.last_job_id == "job-2"
