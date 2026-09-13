"""The mcp_tool adapter, the MCP transport, and the source adapter conformance kit."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fixture_server import CONNECTOR, ITEMS, build_reader_server

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.adapters.mcp_tool_paging import (
    cursor_after_page,
    dig_path,
    next_position,
    page_params,
    set_path,
    tool_arguments,
)
from agent_connector_sdk.adapters.mcp_tool_records import raw_records, source_record
from agent_connector_sdk.contracts import CapabilityDescriptor, SyncCursor
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.ports.session import McpSession, TransportEndpoint
from agent_connector_sdk.ports.source_adapter import SourceAdapter
from agent_connector_sdk.ports.transport import Transport
from agent_connector_sdk.testing.results import (
    ConformanceFailure,
    ConformanceResult,
    SessionFactory,
    assert_conformant,
)
from agent_connector_sdk.testing.source_adapters import (
    Sweep,
    check_capability_descriptor,
    check_checkpoint_resume,
    check_idempotent_rerun,
    check_malformed_input_rejection,
    check_pagination,
    check_provenance_completeness,
    run_source_adapter_suite,
    sweep,
)
from agent_connector_sdk.transports.mcp import McpTransport, client_target
from agent_connector_sdk.transports.mcp_session import (
    McpClientSession,
    McpTransportError,
    decode_tool_result,
)


async def test_mcp_tool_adapter_passes_the_conformance_kit(
    adapter: McpToolSourceAdapter,
    sessions: SessionFactory,
    malformed_sessions: SessionFactory,
) -> None:
    assert isinstance(adapter, SourceAdapter)
    results = await run_source_adapter_suite(adapter, sessions, malformed_sessions)
    assert_conformant(results)
    assert [result.check for result in results] == [
        "capability-descriptor",
        "pagination",
        "checkpoint-resume",
        "idempotent-rerun",
        "malformed-input-rejection",
        "provenance-completeness",
    ]


async def test_sweep_extracts_every_item_in_order(
    adapter: McpToolSourceAdapter, sessions: SessionFactory
) -> None:
    async with sessions() as session:
        result: Sweep = await sweep(adapter, session)
    assert [record.record_id for record in result.records] == [
        item["id"] for item in ITEMS
    ]
    assert result.pages == 3 and result.exhausted
    assert (
        result.cursor is not None and result.cursor.watermark == ITEMS[-1]["published"]
    )


async def test_incremental_extraction_uses_the_watermark(
    adapter: McpToolSourceAdapter, sessions: SessionFactory
) -> None:
    cursor = SyncCursor(stream="demo", watermark=ITEMS[2]["published"])
    async with sessions() as session:
        result = await sweep(adapter, session, cursor=cursor)
    assert [record.record_id for record in result.records] == ["item-4", "item-5"]


async def test_reconcile_diffs_known_ids(
    adapter: McpToolSourceAdapter, sessions: SessionFactory
) -> None:
    async with sessions() as session:
        await adapter.discover(session)
        report = await adapter.reconcile(session, frozenset({"item-1", "gone"}))
    assert report.missing_from_source == ("gone",)
    assert report.unknown_to_sink == ("item-2", "item-3", "item-4", "item-5")


async def test_adapter_fails_closed(
    adapter: McpToolSourceAdapter, sessions: SessionFactory
) -> None:
    async with sessions() as session:
        with pytest.raises(SourceContractError):
            await adapter.extract(session, None)
        drifted = McpToolSourceAdapter(
            adapter._preset, connector=CONNECTOR, tool_schema_sha256="0" * 64
        )
        with pytest.raises(SourceContractError):
            await drifted.discover(session)
        await adapter.discover(session)
        with pytest.raises(SourceContractError):
            await adapter.extract(session, SyncCursor(stream="other"))
    with pytest.raises(ValueError):
        McpToolSourceAdapter(
            adapter._preset, connector=CONNECTOR, tool_schema_sha256=""
        )


def test_paging_helpers() -> None:
    target: dict[str, object] = {"a": "not-a-dict"}
    set_path(target, "a.b", 1)
    assert (
        target == {"a": {"b": 1}}
        and dig_path({"x": [{"y": 2}]}, "x.0.y") == 2
        and dig_path({}, "x.y") is None
    )
    paged = ToolPreset(
        name="p",
        server="s",
        tool="t",
        pagination="offset",
        page_param="offset",
        page_size=2,
        page_size_param="limit",
        page_kind="offset",
        params_style="args",
    )
    assert page_params(paged, {"offset": 6}, None) == {"offset": 6, "limit": 2}
    assert tool_arguments(paged, {"offset": 6}) == {"offset": 6}
    assert next_position(paged, {}, result={}, raw=[{}, {}]) == {"offset": 2}
    assert next_position(paged, {}, result={}, raw=[{}]) is None
    keyset = ToolPreset(
        name="k",
        server="s",
        tool="t",
        pagination="cursor",
        cursor_param="after",
        cursor_record_field="id",
        more_path="truncated",
    )
    assert next_position(keyset, {}, result={"truncated": True}, raw=[{"id": 9}]) == {
        "cursor": 9
    }
    assert (
        next_position(keyset, {}, result={"truncated": False}, raw=[{"id": 9}]) is None
    )
    cursor = cursor_after_page(SyncCursor(stream="k", watermark="b"), (), None)
    assert cursor.watermark == "b" and cursor.position == {}


def test_record_helpers() -> None:
    mapping = ToolPreset(
        name="m", server="s", tool="t", records_path="data", records_is_mapping=True
    )
    assert raw_records(mapping, {"data": {"k1": {"id": 1}}}) == [
        {"source_key": "k1", "id": 1}
    ]
    with pytest.raises(MalformedSourceDataError):
        raw_records(mapping, {"data": {"k1": 3}})
    listing = ToolPreset(name="l", server="s", tool="t")
    with pytest.raises(MalformedSourceDataError):
        raw_records(listing, [1, 2])
    with pytest.raises(MalformedSourceDataError):
        source_record(listing, {"title": "no id"}, connector="c", schema_sha256="x")
    with pytest.raises(MalformedSourceDataError):
        source_record(
            listing, {"id": 1, "blob": object()}, connector="c", schema_sha256="x"
        )


async def test_transport_and_session() -> None:
    transport = McpTransport()
    assert isinstance(transport, Transport)
    assert (
        client_target(TransportEndpoint(url="https://mcp.example.invalid/mcp"))
        == "https://mcp.example.invalid/mcp"
    )
    stdio = client_target(
        TransportEndpoint(command="demo-mcp", args=("--x",), env={"A": "1"})
    )
    assert stdio == {
        "mcpServers": {
            "connector": {"command": "demo-mcp", "args": ["--x"], "env": {"A": "1"}}
        }
    }
    for bad in ({}, {"url": "u", "command": "c"}, {"url": "u", "timeout_seconds": 0}):
        with pytest.raises(ValueError):
            TransportEndpoint(**bad)
    async with transport.session(
        TransportEndpoint(in_process=build_reader_server())
    ) as session:
        assert isinstance(session, McpClientSession) and isinstance(session, McpSession)
        identity = await session.server_identity()
        assert (identity.name, identity.version) == ("demo-mcp", "1.4.0")
        assert "demo_agent" in [prompt.name for prompt in await session.list_prompts()]
        assert (
            await session.read_resource("ontology://demo-agent/demo.ttl")
        ).startswith("@prefix")
        with pytest.raises(McpTransportError):
            await session.call_tool("missing_tool", {})
    assert (
        decode_tool_result(SimpleNamespace(content=[SimpleNamespace(text="plain")]))
        == "plain"
    )
    assert decode_tool_result(
        SimpleNamespace(content=[], structured_content={"a": 1})
    ) == {"a": 1}


class _FakeAdapter:
    kind = "fake"

    def describe(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(kind="other")


async def test_conformance_checks_report_failures(
    adapter: McpToolSourceAdapter, sessions: SessionFactory
) -> None:
    assert not check_capability_descriptor(_FakeAdapter()).passed
    single_page = McpToolSourceAdapter(
        adapter._preset.model_copy(update={"params": {"count": 50}}),
        connector=CONNECTOR,
        tool_schema_sha256=adapter._pinned,
    )
    assert not (await check_pagination(single_page, sessions)).passed
    assert not (await check_checkpoint_resume(single_page, sessions)).passed
    assert (await check_idempotent_rerun(adapter, sessions)).passed
    assert not (await check_malformed_input_rejection(adapter, sessions)).passed
    assert not check_provenance_completeness([]).passed
    with pytest.raises(ConformanceFailure, match="broken"):
        assert_conformant([ConformanceResult("broken", False, "detail")])
