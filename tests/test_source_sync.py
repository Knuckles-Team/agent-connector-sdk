"""Declared connector sources and the source sync runner (SDK-SOURCE-INGEST-R004.19-R004.23)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from agent_connector_sdk.ingest.source_sync import (
    CHECKPOINT_NAMESPACE,
    KvSourceCheckpoints,
    SourceCheckpointState,
    SourceSession,
    SourceSyncError,
    SourceSyncReport,
    SourceSyncRunner,
    SyncBudget,
    checkpoint_key,
    record_digest,
)
from agent_connector_sdk.ingest.sources import (
    DECLARATION_FILE,
    IngestSourceDeclaration,
    IngestSourceSpec,
    ingest_sources_tool_name,
    load_ingest_sources,
    register_ingest_sources_tool,
)
from agent_connector_sdk.mcp.tool_surface import register_tool_surface

ITEMS = [
    {"id": i, "name": f"item-{i}", "updated": f"2026-01-0{i}", "nested": {"x": 1}}
    for i in range(1, 6)
]


def _spec(**overrides: Any) -> IngestSourceSpec:
    values: dict[str, Any] = {
        "source_id": "items",
        "record_type": "FixtureItem",
        "tools": ("fixture_list_items",),
        "records_path": "data",
        "id_field": "id",
        "title_field": "name",
        "cursor_field": "updated",
        "incremental": True,
        "pagination": "page",
        "page_param": "page",
        "page_size_param": "per_page",
        "page_size": 2,
    }
    values.update(overrides)
    return IngestSourceSpec.model_validate(values)


class _Session:
    def __init__(self, items: list[dict[str, Any]], *, read_only: bool = True) -> None:
        self.items = items
        self.read_only = read_only
        self.calls: list[dict[str, Any]] = []
        self.failures = 0

    async def tool_is_read_only(self, name: str) -> bool:
        return self.read_only

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self.calls.append(dict(arguments))
        if self.failures:
            self.failures -= 1
            raise ConnectionError("transient")
        page, size = int(arguments.get("page", 1)), int(arguments.get("per_page", 100))
        return {"data": self.items[(page - 1) * size : page * size]}


class _Ingest:
    def __init__(self) -> None:
        self.batches: list[tuple[Any, Any]] = []

    async def submit(self, binding: Any, changes: Any) -> Any:
        self.batches.append((binding, changes))
        return SimpleNamespace(batch_digest=f"digest-{len(self.batches)}")


class _Checkpoints:
    def __init__(self) -> None:
        self.stored: dict[tuple[str, str], tuple[SourceCheckpointState, int]] = {}
        self.conflict = False

    async def load(self, connector: str, source_id: str) -> Any:
        return self.stored.get(
            (connector, source_id),
            (SourceCheckpointState(connector=connector, source_id=source_id), 0),
        )

    async def store(self, state: SourceCheckpointState, version: int) -> int:
        if self.conflict:
            raise SourceSyncError("checkpoint_conflict", "moved")
        key = (state.connector, state.source_id)
        current = self.stored.get(key, (None, 0))[1]
        assert current == version
        self.stored[key] = (state, version + 1)
        return version + 1


def _runner(session: _Session, ingest: _Ingest, checkpoints: _Checkpoints, **kw: Any):
    async def no_sleep(_seconds: float) -> None:
        return None

    return SourceSyncRunner(
        connector="fixture-mcp",
        server="fixture-mcp",
        session=session,
        ingest=ingest,
        checkpoints=checkpoints,
        sleep=no_sleep,
        **kw,
    )


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.19")
def test_declaration_validates_sources(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cursor_field"):
        _spec(cursor_field=None)
    with pytest.raises(ValueError):
        _spec(tools=())
    with pytest.raises(ValueError, match="unique"):
        IngestSourceDeclaration(connector="c", sources=(_spec(), _spec()))
    assert load_ingest_sources(tmp_path) is None
    path = tmp_path / DECLARATION_FILE
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"connector": "c", "sources": [_spec().model_dump(mode="json")]})
    )
    declaration = load_ingest_sources(tmp_path)
    assert declaration is not None and declaration.source("items") is not None


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.20")
async def test_runner_submits_typed_batches_once() -> None:
    session, ingest, checkpoints = _Session(ITEMS), _Ingest(), _Checkpoints()
    runner = _runner(session, ingest, checkpoints)
    report = await runner.sync(_spec(), job_id="job-1")
    assert report.state == "completed" and report.submitted == 5
    binding, changes = ingest.batches[0]
    assert (binding.connector, binding.stream, binding.tool) == (
        "fixture-mcp",
        "items",
        "fixture_list_items",
    )
    entity = changes.entities[0]
    assert entity.node_type == "FixtureItem" and entity.id == "1"
    assert entity.properties["title"] == "item-1" and "nested" not in entity.properties
    assert changes.cursor == "2026-01-05"
    again = await runner.sync(_spec(), job_id="job-2")
    assert again.submitted == 0 and again.unchanged == 5
    full = await runner.sync(_spec(), mode="full")
    assert full.submitted == 5
    state = await runner.status("items")
    assert state.records == 5 and state.cursor == "2026-01-05"
    assert state.last_job_id is None and state.state == "completed"


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.21")
async def test_tool_surface_serves_declarations(tmp_path: Path) -> None:
    path = tmp_path / DECLARATION_FILE
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {"connector": "fixture-mcp", "sources": [_spec().model_dump(mode="json")]}
        )
    )
    mcp = FastMCP("fixture")
    register_tool_surface(mcp, service="fixture-mcp", package_root=tmp_path)
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        tool = tools["fixture_ingest_sources"]
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        result = await client.call_tool("fixture_ingest_sources", {})
    assert result.data["sources"][0]["source_id"] == "items"
    assert checkpoint_key("fixture-mcp", "items") == "ingest-source/fixture-mcp/items"


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.22")
async def test_runner_refusals_and_budgets() -> None:
    ingest, checkpoints = _Ingest(), _Checkpoints()
    with pytest.raises(SourceSyncError, match="not_read_only"):
        await _runner(_Session(ITEMS, read_only=False), ingest, checkpoints).sync(
            _spec()
        )
    flaky = _Session(ITEMS)
    flaky.failures = 2
    report = await _runner(flaky, ingest, checkpoints).sync(_spec())
    assert report.state == "completed"
    broken = _Session(ITEMS)
    broken.failures = 10
    failed = await _runner(broken, _Ingest(), _Checkpoints()).sync(_spec())
    assert failed.state == "failed" and failed.reason == "tool_failed"
    partial = await _runner(
        _Session(ITEMS), _Ingest(), _Checkpoints(), budget=SyncBudget(max_pages=1)
    ).sync(_spec())
    assert partial.state == "partial" and partial.submitted == 2
    conflicted = _Checkpoints()
    conflicted.conflict = True
    with pytest.raises(SourceSyncError, match="checkpoint_conflict"):
        await _runner(_Session(ITEMS), _Ingest(), conflicted).sync(_spec())


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.23")
async def test_report_binds_receipts() -> None:
    ingest = _Ingest()
    report = await _runner(
        _Session(ITEMS), ingest, _Checkpoints(), budget=SyncBudget(batch_size=2)
    ).sync(_spec())
    assert report.batch_digests == ("digest-1", "digest-2", "digest-3")
    assert report.cursor_before is None and report.cursor_after == "2026-01-05"
    dumped = report.model_dump_json()
    assert "item-1" not in dumped


class _KvClient:
    """The engine client ``_send`` seam the generated KV methods call."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, bool], tuple[bytes, int]] = {}

    async def _send(
        self, method: str, params: Any, graph: Any, *, idempotency_key: Any = None
    ) -> Any:
        key = (params["namespace"], params["key"], bool(params.get("shared")))
        if method == "KvGet":
            row = self.rows.get(key)
            return None if row is None else {"value": row[0], "version": row[1]}
        version = self.rows.get(key, (b"", 0))[1]
        if params["expected_version"] != version:
            return {"swapped": False, "version": version}
        self.rows[key] = (params["new"], version + 1)
        return {"swapped": True, "version": version + 1}


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.21")
async def test_kv_checkpoints_use_the_shared_scope() -> None:
    client = _KvClient()
    store = KvSourceCheckpoints(client)
    state, version = await store.load("fixture-mcp", "items")
    assert version == 0 and state.state == "never"
    version = await store.store(state.model_copy(update={"cursor": "c1"}), version)
    loaded, again = await store.load("fixture-mcp", "items")
    assert (loaded.cursor, again) == ("c1", version)
    assert list(client.rows) == [
        (CHECKPOINT_NAMESPACE, checkpoint_key("fixture-mcp", "items"), True)
    ]
    with pytest.raises(SourceSyncError, match="checkpoint_conflict"):
        await store.store(loaded, 0)
    assert ingest_sources_tool_name("fixture") == "fixture_ingest_sources"
    assert len(record_digest({"a": 1})) == 64
    assert isinstance(_Session(ITEMS), SourceSession)
    assert (
        SourceSyncReport(
            connector="c", source_id="s", mode="full", state="completed"
        ).submitted
        == 0
    )
    mcp = FastMCP("direct")
    declaration = IngestSourceDeclaration(connector="c", sources=(_spec(),))
    assert register_ingest_sources_tool(mcp, "direct", declaration) == (
        "direct_ingest_sources"
    )
