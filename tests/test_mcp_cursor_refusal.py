"""A repeated continuation cannot advance a durable MCP source checkpoint."""

import pytest
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
from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.testing.sinks import InMemorySink


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.50")
@pytest.mark.parametrize("kind", ["event", "generic"])
async def test_repeated_cursor_refuses_page_before_checkpoint(kind):
    secret_cursor = "cursor-private-fixture"  # sanitizer:ignore - synthetic cursor
    if kind == "event":
        preset = _preset("rum-stream", "rum_events")
        adapter = _adapter(rum_source_adapter, preset)
        first, second = _rum_event("first"), _rum_event("second", offset_seconds=1)
    else:
        preset = ToolPreset(
            name="rum-stream",
            server="observability-mcp",
            tool="rum_events",
            records_path="events",
            id_field="id",
            pagination="cursor",
            cursor_param="cursor",
            cursor_path="cursor",
        )
        adapter = McpToolSourceAdapter(
            preset,
            connector=CONNECTOR,
            mapping_reference=f"connector:{CONNECTOR}#mappings/Event",
        )
        first, second = {"id": "first"}, {"id": "second"}
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool),
        pages=[
            _page(first, cursor=secret_cursor),
            _page(second, cursor=secret_cursor),
            _page(second),
        ],
    )
    sink = InMemorySink()
    target = SyncTarget(CONNECTOR, sink, max_pages=3)
    with pytest.raises(SourceContractError, match="cursor did not advance") as failure:
        await sync_stream(session, adapter, target)
    assert secret_cursor not in str(failure.value)
    status = await sink.source_status(CONNECTOR, preset.name)
    assert status.accepted_checkpoint.position == {"cursor": secret_cursor}
    assert status.accepted_checkpoint.watermark is None
    assert len(sink.batches) == 1
    outcome = await sync_stream(session, adapter, target)
    assert outcome.exhausted
    assert sum(len(batch.records) for batch in sink.batches.values()) == 2


def test_explicit_end_with_repeated_cursor_is_allowed():
    from agent_connector_sdk.adapters.mcp_tool_paging import next_position

    preset = ToolPreset(
        name="s",
        server="s",
        tool="t",
        pagination="cursor",
        cursor_param="cursor",
        cursor_path="cursor",
        more_path="has_more",
    )
    assert (
        next_position(
            preset,
            {"cursor": "same"},
            result={"cursor": "same", "has_more": False},
            raw=[{"id": "x"}],
        )
        is None
    )


def test_empty_cursor_page_still_requires_progress():
    from agent_connector_sdk.adapters.mcp_tool_paging import next_position

    preset = ToolPreset(
        name="s",
        server="s",
        tool="t",
        pagination="cursor",
        cursor_param="cursor",
        cursor_path="cursor",
    )
    with pytest.raises(SourceContractError, match="cursor did not advance"):
        next_position(preset, {"cursor": "old"}, result={"cursor": "old"}, raw=[])
    assert next_position(
        preset, {"cursor": "old"}, result={"cursor": "next"}, raw=[]
    ) == {"cursor": "next"}
    assert (
        next_position(preset, {"cursor": "old"}, result={"cursor": None}, raw=[])
        is None
    )
