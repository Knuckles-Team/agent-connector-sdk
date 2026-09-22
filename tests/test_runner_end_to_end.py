"""The runner end to end against the freshrss-agent and archivebox-api fixtures.

Everything commits into ``InMemorySink``; epistemic-graph import is wave W1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from fleet_fixtures import (
    ARCHIVEBOX_CURRENT_SHA256,
    ARCHIVEBOX_ENUM_SHA256,
    ARCHIVEBOX_ROOT,
    FRESHRSS_CURRENT_SHA256,
    FRESHRSS_ENUM_SHA256,
    FRESHRSS_READING_LIST,
    FRESHRSS_ROOT,
    FakeArchiveBox,
    FakeFreshRss,
    archivebox_snapshots,
    build_archivebox_server,
    build_enumerated_archivebox_server,
    build_enumerated_freshrss_server,
    build_freshrss_server,
    freshrss_items,
)
from runner_support import (
    ListRegistry,
    RecordingSink,
    archivebox_descriptor,
    capture_runner_logs,
    eventually,
    freshrss_descriptor,
    freshrss_runner,
    in_process,
    logged,
    services,
)

from agent_connector_sdk.certify.checkout import load_checkout
from agent_connector_sdk.certify.verdicts import PinStatus, tool_verdicts
from agent_connector_sdk.manifest.live_contract import (
    validate_live_tool_contract,
    validate_preset_tool_contract,
)
from agent_connector_sdk.mcp.change_events import (
    announce_content_changed,
    announce_resource_updated,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.supervisor import ConnectorSyncRunner
from agent_connector_sdk.transports.mcp import McpTransport

LAST_PUBLISHED = str(freshrss_items(249, 1)[0]["published"])


async def test_current_fleet_schemas_require_enumeration_migration() -> None:
    for current, future, root, tool, current_pin, future_pin in (
        (
            build_freshrss_server(FakeFreshRss([])),
            build_enumerated_freshrss_server(FakeFreshRss([])),
            FRESHRSS_ROOT,
            "freshrss_reader",
            FRESHRSS_CURRENT_SHA256,
            FRESHRSS_ENUM_SHA256,
        ),
        (
            build_archivebox_server(FakeArchiveBox([])),
            build_enumerated_archivebox_server(FakeArchiveBox([])),
            ARCHIVEBOX_ROOT,
            "archivebox_core",
            ARCHIVEBOX_CURRENT_SHA256,
            ARCHIVEBOX_ENUM_SHA256,
        ),
    ):
        checkout = load_checkout(root)
        async with McpTransport().session(
            TransportEndpoint(in_process=current)
        ) as session:
            tools = await session.list_tools()
            current_contract = validate_live_tool_contract(
                tools,
                tool_name=tool,
                expected_schema_sha256=current_pin,
            )
            (current_verdict,) = tool_verdicts(checkout, tools)
        assert current_contract.compatibility_sha256 == current_pin
        assert current_verdict.status is PinStatus.TOOL_UNAVAILABLE
        assert "does not enumerate" in current_verdict.defect
        async with McpTransport().session(
            TransportEndpoint(in_process=future)
        ) as session:
            tools = await session.list_tools()
            future_contract = validate_preset_tool_contract(
                tools,
                tool_name=tool,
                presets=tuple(checkout.presets.values()),
                expected_schema_sha256=future_pin,
            )
            (future_verdict,) = tool_verdicts(checkout, tools)
        assert future_contract.compatibility_sha256 == future_pin
        assert future_verdict.status is PinStatus.MATCH
        assert future_verdict.live == future_pin


async def test_provisioning_is_a_noop_when_the_pack_digest_is_unchanged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture_runner_logs(caplog)
    freshrss = FakeFreshRss(freshrss_items(0, 250))
    archive = FakeArchiveBox(archivebox_snapshots(250))
    servers: dict[str, object] = {
        "freshrss-agent": build_enumerated_freshrss_server(freshrss),
        "archivebox-api": build_enumerated_archivebox_server(archive),
    }
    sink = RecordingSink()
    registry = ListRegistry(freshrss_descriptor(), archivebox_descriptor())
    runner = ConnectorSyncRunner(registry, services(sink, in_process(servers)))
    everything = {"freshrss-agent": True, "archivebox-api": True}
    assert await runner.run_once() == everything
    kinds = {
        entry.kind.value
        for pack in sink.inner.packs.values()
        for entry in pack.archive.entries
    }
    assert sink.imports == 2 and kinds == {
        "tool",
        "skill",
        "prompt",
        "ontology",
        "manifest",
    }
    assert len(sink.record_ids("freshrss-agent")) == 250
    assert len(sink.record_ids("archivebox-api")) == 250 and archive.pages == [0, 1, 2]
    assert await runner.run_once() == everything
    assert sink.imports == 4 and len(logged(caplog, "pack_unchanged")) == 2
    assert freshrss.calls[-1]["newer_than"] == LAST_PUBLISHED
    second_pass = logged(caplog, "stream_synced")[2:]
    assert [event["records"] for event in second_pass] == [0, 0]


async def test_sync_resumes_from_the_committed_checkpoint_after_a_crash(
    tmp_path: Path,
) -> None:
    archive = FakeArchiveBox(archivebox_snapshots(250))
    endpoints = in_process(
        {"archivebox-api": build_enumerated_archivebox_server(archive)}
    )
    crashing = RecordingSink(crash_on=2)
    registry = ListRegistry(archivebox_descriptor())
    first = ConnectorSyncRunner(registry, services(crashing, endpoints))
    assert await first.run_once() == {"archivebox-api": False}
    committed = crashing.inner.statuses[
        (
            "archivebox-api",
            "archivebox-snapshots",
        )
    ].accepted_checkpoint
    assert committed is not None and committed.position == {"page": 1}
    assert len(crashing.inner.batches) == 1
    recovered = RecordingSink(crashing.inner)
    resumed = ConnectorSyncRunner(registry, services(recovered, endpoints))
    assert await resumed.run_once() == {"archivebox-api": True}
    assert archive.pages == [0, 1, 1, 2] and recovered.imports == 1
    assert len(recovered.record_ids("archivebox-api")) == 250
    final = recovered.inner.statuses[
        (
            "archivebox-api",
            "archivebox-snapshots",
        )
    ].accepted_checkpoint
    assert final is not None and final.position == {}
    assert final.watermark == archivebox_snapshots(250)[-1]["modified_at"]


async def test_change_events_drive_provisioning_and_incremental_sync(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture_runner_logs(caplog)
    freshrss = FakeFreshRss(freshrss_items(0, 250))
    server = build_enumerated_freshrss_server(freshrss)
    sink = RecordingSink()
    runner = freshrss_runner(sink, tmp_path, server)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner.run_forever)
        await eventually(lambda: bool(logged(caplog, "change_subscription")))
        assert logged(caplog, "change_subscription")[0]["listening"] is True
        assert sink.imports == 1 and len(sink.record_ids("freshrss-agent")) == 250

        @server.tool()
        def freshrss_unread_count() -> dict[str, Any]:
            """Count unread items."""
            return {"unread": 0}

        await announce_content_changed(server)
        await eventually(lambda: len(sink.inner.packs) == 2)
        freshrss.items.extend(freshrss_items(250, 5))
        await announce_resource_updated(server, FRESHRSS_READING_LIST)
        await eventually(lambda: len(sink.record_ids("freshrss-agent")) == 255)
        tasks.cancel_scope.cancel()
    assert freshrss.calls[-1]["newer_than"] == LAST_PUBLISHED
    assert sink.imports == 3 and freshrss_unread_count() == {"unread": 0}
    assert logged(caplog, "pack_unchanged")


async def test_without_listen_the_schedule_drives_sync(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture_runner_logs(caplog)
    freshrss = FakeFreshRss(freshrss_items(0, 3))
    server = build_enumerated_freshrss_server(freshrss, listen=False)
    sink = RecordingSink()
    runner = freshrss_runner(sink, tmp_path, server, interval_seconds=0.1)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner.run_forever)
        await eventually(lambda: bool(logged(caplog, "change_subscription")))
        assert logged(caplog, "change_subscription")[0]["listening"] is False
        freshrss.items.extend(freshrss_items(3, 2))
        await eventually(lambda: len(sink.record_ids("freshrss-agent")) == 5)
        tasks.cancel_scope.cancel()
    assert sink.imports == 2 and logged(caplog, "pack_unchanged")
