"""Exact event-page replay against the graph's durable checkpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from epistemic_graph.connector_pack import (
    ConnectorPackArchiveBuilder,
    ConnectorPackClient,
    ConnectorPackEntryContent,
)
from epistemic_graph.generated.connector_pack import PackEntryKind, PackProducer
from live_engine import PRINCIPAL, TENANT, live_ingest, scoped_client  # noqa: F401
from test_contracts_and_sink import _catalog, _mutation_context
from test_event_feeds import (
    CONNECTOR,
    FakeEventSession,
    _adapter,
    _page,
    _preset,
    _rum_event,
    _tool_descriptor,
)

from agent_connector_sdk.adapters.event_feed_bindings import rum_source_adapter
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.sinks import InMemorySink


async def _sync(sink, event):
    preset = _preset("rum-stream", "rum_events")
    adapter = _adapter(rum_source_adapter, preset)
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool), pages=[_page(event)]
    )
    return await sync_stream(session, adapter, SyncTarget(CONNECTOR, sink, max_pages=1))


@pytest.mark.spec("SCION-OBSERVABILITY-FEEDS-R001.6")
async def test_exact_page_replay_keeps_distinct_same_time_event():
    sink = InMemorySink()
    first = _rum_event("first")
    other = _rum_event("other")
    initial = await _sync(sink, first)
    replay = await _sync(sink, first)
    distinct = await _sync(sink, other)
    assert (initial.accepted, replay.accepted, distinct.accepted) == (1, 0, 1)
    assert replay.checkpoint == initial.checkpoint
    assert distinct.checkpoint != initial.checkpoint
    assert distinct.checkpoint.watermark == initial.checkpoint.watermark
    assert sum(len(batch.records) for batch in sink.batches.values()) == 2


async def _import_mapping(client):
    context = _mutation_context().model_copy(update={"tenant_id": TENANT})
    key = "event-replay-test:bind"
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
                    "Event": {
                        "ontology_class": "Document",
                        "fields": {"provider_event_id": "identifier"},
                    }
                },
            }
        ).encode(),
        output_schema=b'{"type":"object"}',
    )
    archive = ConnectorPackArchiveBuilder.build(server, [resource])
    result = await ConnectorPackClient(client).import_pack(
        archive,
        connector=CONNECTOR,
        server_package_version="1.0.0",
        producer=PackProducer(name="event-replay-test", version="1"),
        catalog=_catalog(),
        context=context,
    )
    assert result.result == "imported", result
    return context


async def _exercise_graph():
    client = await scoped_client(["*"])
    try:
        context = await _import_mapping(client)

        async def authority(_connector):
            return _catalog(), context

        sink = EpistemicGraphSink(client, authority)
        first = _rum_event("first", tenant_id=TENANT)
        other = _rum_event("other", tenant_id=TENANT)
        initial = await _sync(sink, first)
        status = await sink.source_status(CONNECTOR, "rum-stream")
        replay = await _sync(sink, first)
        after_replay = await sink.source_status(CONNECTOR, "rum-stream")
        distinct = await _sync(sink, other)
        final = await sink.source_status(CONNECTOR, "rum-stream")
        older_replay = await _sync(sink, first)
        rows = await client.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        return (
            initial,
            status,
            replay,
            after_replay,
            distinct,
            final,
            older_replay,
            rows,
        )
    finally:
        await client.close()


@pytest.mark.spec("SCION-OBSERVABILITY-FEEDS-R001.6")
def test_fresh_worker_replays_against_real_graph(live_ingest):  # noqa: F811
    result = asyncio.run_coroutine_threadsafe(
        _exercise_graph(), live_ingest._loop
    ).result(30)
    initial, status, replay, after_replay, distinct, final, older_replay, rows = result
    assert (initial.accepted, replay.accepted, distinct.accepted) == (1, 0, 1)
    assert (
        status.last_receipt_id
        and after_replay.last_receipt_id == status.last_receipt_id
    )
    assert after_replay.accepted_checkpoint == status.accepted_checkpoint
    assert final.last_receipt_id != status.last_receipt_id
    assert final.accepted_checkpoint.watermark == status.accepted_checkpoint.watermark
    assert older_replay.accepted == 1
    events = [row["n"] for row in rows if row["n"].get("source_stream") == "rum-stream"]
    assert sorted(event["source_record_id"] for event in events) == ["first", "other"]


async def _prepare_restart_graph():
    client = await scoped_client(["*"])
    try:
        await _import_mapping(client)
    finally:
        await client.close()


async def _read_restart_graph():
    client = await scoped_client(["*"])
    try:
        rows = await client.query.cypher_read("MATCH (n) RETURN n LIMIT 100")
        return [
            row["n"] for row in rows if row["n"].get("source_stream") == "rum-stream"
        ]
    finally:
        await client.close()


@pytest.mark.spec("SCION-OBSERVABILITY-FEEDS-R001.3")
def test_restart_worker_process_against_real_graph(live_ingest):  # noqa: F811
    import json
    import subprocess
    import sys
    from pathlib import Path

    from live_engine import _LIVE

    loop = live_ingest._loop
    asyncio.run_coroutine_threadsafe(_prepare_restart_graph(), loop).result(30)
    script = Path(__file__).with_name("event_restart_worker.py")

    def worker():
        result = subprocess.run(
            [sys.executable, str(script), str(_LIVE["socket"])],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(result.stdout)

    first = worker()
    second = worker()
    assert first["accepted"] == 1 and first["receipt"]
    assert second == {"accepted": 0, "receipt": first["receipt"]}
    events = asyncio.run_coroutine_threadsafe(_read_restart_graph(), loop).result(30)
    assert [event["source_record_id"] for event in events] == ["restart-proof"]
