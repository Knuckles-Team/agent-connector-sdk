"""Optional real-engine proof for checkpoint-only source progress."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from live_engine import live_ingest, scoped_client  # noqa: F401
from test_event_feeds import CONNECTOR
from test_event_replay_checkpoint import _import_mapping

from agent_connector_sdk.ingest import (
    IngestBinding,
    KnowledgeIngest,
    RecordMap,
    SourceStream,
)
from agent_connector_sdk.ingest.transport import EpistemicGraphIngestTransport


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.33")
def test_empty_page_checkpoint_on_real_graph(live_ingest: Any) -> None:  # noqa: F811
    binding = IngestBinding(connector=CONNECTOR, stream="empty-window")
    stream = SourceStream(binding, {"item": RecordMap("Item", "demo:{_id}")})

    async def check() -> None:
        client = await scoped_client(["*"])
        try:
            await _import_mapping(client)
            service = KnowledgeIngest(EpistemicGraphIngestTransport(client))

            async def fetch(
                cursor: str | None,
            ) -> tuple[list[dict[str, str]], str | None]:
                if cursor is None:
                    return [], "next-window"
                raise RuntimeError("interrupted")

            with pytest.raises(RuntimeError, match="interrupted"):
                await stream.sync("item", fetch, ingest=service)
            assert await service.accepted_cursor(binding) == "next-window"
        finally:
            await client.close()

    asyncio.run_coroutine_threadsafe(check(), live_ingest._loop).result(30)
