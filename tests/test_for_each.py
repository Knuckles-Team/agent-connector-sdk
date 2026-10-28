"""Per-parent fan-out of declared sources (SDK-SOURCE-INGEST-R004.28)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import FastMCP
from pydantic import ValidationError

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.ingest.for_each import MAX_FAN_OUT, ForEach
from agent_connector_sdk.ingest.source_sync import (
    SourceCheckpointState,
    SourceSyncRunner,
    SyncBudget,
)
from agent_connector_sdk.ingest.sources import (
    IngestSourceDeclaration,
    IngestSourceSpec,
)
from agent_connector_sdk.manifest.declaration import contract_from_declaration
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

PARENTS = [{"id": f"p{i}", "name": f"project-{i}"} for i in range(1, 4)]
CHILDREN = {
    "p1": [{"id": "a1", "project": "p1"}, {"id": "a2", "project": "p1"}],
    "p2": [],
    "p3": [{"id": "c1", "project": "p3"}],
}
LINK = {"source": "projects", "argument": "project_id", "field": "id"}


def _source(source_id: str, tool: str, **extra: Any) -> IngestSourceSpec:
    return IngestSourceSpec.model_validate(
        {
            "source_id": source_id,
            "record_type": "Thing",
            "tools": (tool,),
            "records_path": "data",
            "id_field": "id",
            **extra,
        }
    )


def _declaration(**child: Any) -> tuple[IngestSourceSpec, IngestSourceSpec]:
    return (
        _source("projects", "list_projects"),
        _source("items", "list_items", for_each=LINK, **child),
    )


class _Session:
    def __init__(self, parents: list[dict[str, Any]] = PARENTS) -> None:
        self.parents = parents
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def tool_is_read_only(self, name: str) -> bool:
        return True

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self.calls.append((name, dict(arguments)))
        if name == "list_projects":
            return {"data": self.parents}
        return {"data": CHILDREN.get(arguments["project_id"], [])}


class _Ingest:
    def __init__(self) -> None:
        self.entities: list[Any] = []

    async def submit(self, binding: Any, changes: Any) -> Any:
        self.entities += list(changes.entities)
        return SimpleNamespace(batch_digest="d")


class _Checkpoints:
    async def load(self, connector: str, source_id: str) -> Any:
        return SourceCheckpointState(connector=connector, source_id=source_id), 0

    async def store(self, state: SourceCheckpointState, version: int) -> int:
        return version + 1


def _runner(session: _Session, ingest: _Ingest, **kw: Any) -> SourceSyncRunner:
    async def no_sleep(_seconds: float) -> None:
        return None

    return SourceSyncRunner(
        connector="c",
        server="c",
        session=session,
        ingest=ingest,
        checkpoints=_Checkpoints(),
        sleep=no_sleep,
        **kw,
    )


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.28")
async def test_child_runs_once_per_parent_record() -> None:
    projects, items = _declaration()
    session, ingest = _Session(), _Ingest()
    report = await _runner(session, ingest).sync(
        items, sources={s.source_id: s for s in (projects, items)}
    )
    assert report.state == "completed" and report.submitted == 3
    assert [e.id for e in ingest.entities] == ["a1", "a2", "c1"]
    child_calls = [a for n, a in session.calls if n == "list_items"]
    assert child_calls == [
        {"project_id": "p1"},
        {"project_id": "p2"},
        {"project_id": "p3"},
    ]


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.28")
async def test_missing_parent_and_cycle_are_typed_refusals() -> None:
    _, items = _declaration()
    run = await _runner(_Session(), _Ingest()).sync(items, sources={"items": items})
    assert run.state == "failed" and run.reason == "unknown_parent_source"
    with pytest.raises(ValidationError, match="unknown_parent_source"):
        IngestSourceDeclaration(connector="c", sources=(items,))
    a = _source("a", "t", for_each={"source": "b", "argument": "x"})
    b = _source("b", "t", for_each={"source": "a", "argument": "x"})
    with pytest.raises(ValidationError, match="for_each_cycle"):
        IngestSourceDeclaration(connector="c", sources=(a, b))
    own = _source("s", "t", for_each={"source": "s", "argument": "x"})
    with pytest.raises(ValidationError, match="for_each_cycle"):
        IngestSourceDeclaration(connector="c", sources=(own,))
    cyclic = await _runner(_Session(), _Ingest()).sync(a, sources={"a": a, "b": b})
    assert cyclic.state == "failed" and cyclic.reason == "for_each_cycle"


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.28")
async def test_fan_out_is_capped() -> None:
    projects, items = _declaration()
    session = _Session([{"id": f"p{i}"} for i in range(6)])
    report = await _runner(session, _Ingest(), budget=SyncBudget(max_fan_out=5)).sync(
        items, sources={s.source_id: s for s in (projects, items)}
    )
    assert report.state == "failed" and report.reason == "fan_out_exceeded"
    assert not [c for c in session.calls if c[0] == "list_items"]
    assert SyncBudget().max_fan_out == MAX_FAN_OUT


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.28")
def test_for_each_is_in_the_served_schema() -> None:
    schema = IngestSourceDeclaration.model_json_schema()
    spec = schema["$defs"]["IngestSourceSpec"]["properties"]["for_each"]
    assert "ForEach" in json.dumps(spec)
    assert set(schema["$defs"]["ForEach"]["properties"]) == {
        "source",
        "argument",
        "field",
    }
    assert ForEach(source="p", argument="a").field == "id"


def _fan_server() -> FastMCP:
    mcp = FastMCP("fan")

    @mcp.tool(annotations={"readOnlyHint": True})
    def list_projects() -> dict:
        return {"data": PARENTS}

    @mcp.tool(annotations={"readOnlyHint": True})
    def list_items(project_id: str, page: int = 0) -> dict:
        rows = CHILDREN.get(project_id, [])
        return {"data": rows[page * 1 : page * 1 + 1]}

    return mcp


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.28")
async def test_preset_adapter_fans_out_and_pages_each_parent() -> None:
    sources = (
        _source(
            "projects",
            "list_projects",
            preset={"doc_type": "project", "params_style": "args"},
        ),
        _source(
            "items",
            "list_items",
            for_each=LINK,
            pagination="page",
            page_param="page",
            page_size=1,
            start_page=0,
            preset={"doc_type": "item", "params_style": "args"},
        ),
    )
    contract = contract_from_declaration(
        IngestSourceDeclaration(
            connector="fan",
            sources=sources,
            schema_mappings={"Thing": {"ontology_class": "Thing", "fields": {}}},
        )
    )
    assert contract is not None
    specs = {s.preset: s for s in contract.sync}
    adapter = McpToolSourceAdapter.from_sync_spec(
        specs["items"],
        connector="fan",
        mapping_reference="connector:fan",
        schema_mappings=contract.schema_mappings,
        parents=specs,
    )
    async with McpTransport().session(
        TransportEndpoint(in_process=_fan_server())
    ) as session:
        await adapter.discover(session)
        checkpoint = None
        ids: list[str] = []
        for _ in range(20):
            page = await adapter.extract(session, checkpoint)
            ids += [r.record_id for r in page.records]
            if page.exhausted:
                break
            checkpoint = page.checkpoint
        else:
            raise AssertionError("sweep never ended")
    assert [i.rsplit("/", 1)[-1] for i in ids] == ["a1", "a2", "c1"]
    assert page.checkpoint.position == {}


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.28")
def test_preset_adapter_refuses_unknown_parent() -> None:
    items = _source("items", "list_items", for_each=LINK, preset={"doc_type": "item"})
    from agent_connector_sdk.manifest.declaration import _sync_spec

    spec = _sync_spec(items, "fan")
    with pytest.raises(ValueError, match="unknown_parent_source"):
        McpToolSourceAdapter.from_sync_spec(
            spec,
            connector="fan",
            mapping_reference="connector:fan",
            parents={"items": spec},
        )


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.28")
def test_check_for_each_and_parent_presets_refuse_by_code() -> None:
    from agent_connector_sdk.adapters import mcp_tool_fanout
    from agent_connector_sdk.ingest.for_each import ForEachRefusal, check_for_each
    from agent_connector_sdk.manifest.presets import ToolPreset

    link = ForEach(source="b", argument="x")
    with pytest.raises(ForEachRefusal) as missing:
        check_for_each({"a": link})
    assert missing.value.reason == "unknown_parent_source"
    back = ForEach(source="a", argument="x")
    with pytest.raises(ForEachRefusal) as cycle:
        check_for_each({"a": link, "b": back})
    assert cycle.value.reason == "for_each_cycle"
    child = ToolPreset.from_mapping(
        "items",
        {"tool": "t", "server": "s", "for_each": {"source": "x", "argument": "p"}},
    )
    with pytest.raises(ForEachRefusal, match="unknown_parent_source"):
        mcp_tool_fanout.check_parents(child, {})
    assert mcp_tool_fanout.FAN_KEY == "__fan"
    assert callable(mcp_tool_fanout.parent_values)
    assert callable(mcp_tool_fanout.extract_fanned)


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.53")
async def test_fan_out_limit_refuses_before_requesting_another_parent_page() -> None:
    projects = _source(
        "projects", "list_projects", pagination="page", page_param="page", page_size=2
    )
    items = _source("items", "list_items", for_each=LINK)
    session = _Session([{"id": f"p{i}"} for i in range(6)])
    report = await _runner(session, _Ingest(), budget=SyncBudget(max_fan_out=5)).sync(
        items, sources={s.source_id: s for s in (projects, items)}
    )
    assert report.state == "failed" and report.reason == "fan_out_exceeded"
    assert [name for name, _ in session.calls] == ["list_projects"]
