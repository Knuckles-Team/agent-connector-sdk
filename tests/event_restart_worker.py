"""One synthetic worker process for the isolated graph restart test."""

from __future__ import annotations

import asyncio
import json
import sys

from epistemic_graph import EpistemicGraphClient
from live_engine import _SECRET, GRAPH, TENANT, _context
from test_contracts_and_sink import _catalog, _mutation_context
from test_event_feeds import CONNECTOR, _rum_event
from test_event_replay_checkpoint import _sync

from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink


async def run(socket_path: str) -> None:
    client = await EpistemicGraphClient.connect(
        socket_path=socket_path,
        auth_secret=_SECRET,
        graph_name=GRAPH,
        verified_context=_context(["test"], ["*"]),
    )
    try:

        async def authority(_connector: str):
            return _catalog(), _mutation_context().model_copy(
                update={"tenant_id": TENANT}
            )

        sink = EpistemicGraphSink(client, authority)
        result = await _sync(sink, _rum_event("restart-proof", tenant_id=TENANT))
        status = await sink.source_status(CONNECTOR, "rum-stream")
        print(
            json.dumps({"accepted": result.accepted, "receipt": status.last_receipt_id})
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1]))
