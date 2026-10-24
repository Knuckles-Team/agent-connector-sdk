"""Cursor strategies, keyed projection, size and guard hooks, batching and ingest tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from fastmcp import Client, FastMCP

from agent_connector_sdk.ingest import (
    ChangeSet,
    CursorStrategy,
    Entity,
    HighWaterCursor,
    IngestBinding,
    IngestError,
    IngestTool,
    KeysetCursor,
    Mapped,
    OffsetCursor,
    Pseudonymizer,
    RecordMap,
    Relationship,
    SourceStream,
    TimeWindowCursor,
    ingest_registration,
)
from agent_connector_sdk.ingest.tools import INGEST_TOOL_TAGS

BINDING = IngestBinding(connector="demo-mcp", stream="demo")


class _Ingest:
    def __init__(self, cursor: str | None = None) -> None:
        self.cursor = cursor
        self.submitted: list[ChangeSet] = []
        self.bindings: list[IngestBinding] = []

    async def submit(self, binding: IngestBinding, changes: ChangeSet) -> Any:
        self.bindings.append(binding)
        self.submitted.append(changes)
        self.cursor = changes.cursor or self.cursor
        return SimpleNamespace(
            affected_count=len(changes.entities) + len(changes.documents),
            relationship_count=len(changes.relationships),
        )

    async def accepted_cursor(self, binding: IngestBinding) -> str | None:
        return self.cursor


def _run(coro: Any) -> Any:
    async def main() -> Any:
        return await coro

    return anyio.run(main)


def _stream(**options: Any) -> SourceStream:
    return SourceStream(BINDING, {"row": RecordMap("Row", "demo:{_id}")}, **options)


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.33")
def test_offset_keyset_and_window_strategies_advance_and_stop() -> None:
    offset: CursorStrategy = OffsetCursor(2)
    assert offset.first() == "0"
    assert offset.advance([{}, {}], "0") == "2"
    assert offset.advance([{}, {}], "2") == "4"
    assert offset.advance([{}], "4") is None
    keyset = KeysetCursor("Key", 2)
    assert keyset.first() is None
    assert keyset.advance([{"Key": "a"}, {"Key": "b"}], None) == "b"
    assert keyset.advance([{"Key": "a"}], "b") is None
    with pytest.raises(IngestError):
        keyset.advance([{"Key": "a"}, {}], None)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    window = TimeWindowCursor(start, timedelta(days=1), end=start + timedelta(days=3))
    assert window.first() == start.isoformat()
    assert (
        window.advance([], start.isoformat()) == (start + timedelta(days=1)).isoformat()
    )
    assert window.advance([], (start + timedelta(days=2)).isoformat()) is None
    with pytest.raises(IngestError):
        OffsetCursor(0)
    with pytest.raises(IngestError):
        TimeWindowCursor(start, timedelta(0))


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.33")
def test_sync_with_a_strategy_checkpoints_each_window_and_resumes() -> None:
    rows = [{"id": str(n)} for n in range(5)]
    seen: list[str | None] = []

    async def fetch(cursor: str | None) -> Any:
        seen.append(cursor)
        offset = int(cursor or 0)
        return rows[offset : offset + 2]

    sink = _Ingest()
    out = _run(_stream().sync("row", fetch, strategy=OffsetCursor(2), ingest=sink))
    assert out == {"nodes": 5, "edges": 0}
    assert seen == ["0", "2", "4"]
    assert [c.cursor for c in sink.submitted] == ["2", "4", None]
    resumed = _Ingest(cursor="4")
    seen.clear()
    _run(_stream().sync("row", fetch, strategy=OffsetCursor(2), ingest=resumed))
    assert seen == ["4"]


KEY = b"k" * 32


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.34")
def test_projection_pseudonymizes_ids_edges_and_redacts_properties() -> None:
    pseudo = Pseudonymizer("demo-mcp", "demo", KEY, frozenset({"email"}))
    stream = _stream(projection=pseudo.project)
    sink = _Ingest()
    changes = ChangeSet(
        entities=(
            Entity("u1", "Person", {"name": "Ada", "email": "a@b.example"}),
            Entity("m1", "Message", {"subject": "s"}),
        ),
        relationships=(Relationship("m1", "u1", "sentBy", {"email": "x"}),),
    )
    _run(stream.submit(changes, ingest=sink))
    (sent,) = sink.submitted
    person, message = sent.entities
    assert person.id == pseudo.opaque_id("Person", "u1")
    assert person.id.startswith("demo:Person:") and "u1" not in person.id
    assert dict(person.properties) == {"name": "Ada"}
    edge = sent.relationships[0]
    assert (edge.source, edge.target) == (message.id, person.id)
    assert edge.properties is None
    assert pseudo.opaque_id("Person", "u1") != Pseudonymizer(
        "other-mcp", "demo", KEY
    ).opaque_id("Person", "u1")


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.34")
def test_pseudonymizer_refuses_a_short_key_and_an_empty_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(IngestError):
        Pseudonymizer("demo-mcp", "demo", b"short")
    with pytest.raises(IngestError):
        Pseudonymizer("demo-mcp", "demo", KEY).opaque_id("Person", "")
    monkeypatch.setenv("DEMO_KEY", "k" * 32)
    made = Pseudonymizer.from_setting("demo-mcp", "demo", "DEMO_KEY", redact=["x"])
    assert made.key == KEY and made.redact == {"x"}


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.34")
def test_guard_size_limit_scope_and_receipt() -> None:
    guarded: list[ChangeSet] = []

    def guard(binding: IngestBinding, changes: ChangeSet) -> None:
        guarded.append(changes)
        if any(e.id == "bad" for e in changes.entities):
            raise IngestError("privacy guard changed identity")

    stream = _stream(before_submit=guard, max_records=2)
    sink = _Ingest()
    with pytest.raises(IngestError):
        _run(stream.entities([{"id": "bad", "node_type": "T"}], ingest=sink))
    with pytest.raises(IngestError):
        _run(
            stream.entities(
                [{"id": str(n), "node_type": "T"} for n in range(3)], ingest=sink
            )
        )
    assert not sink.submitted
    receipt = _run(
        stream.submit_receipt(ChangeSet(entities=(Entity("a", "T"),)), ingest=sink)
    )
    assert receipt.affected_count == 1
    scoped = stream.scoped("acct1", server="Demo", strict_schema=True)
    _run(scoped.entities([{"id": "a", "node_type": "T"}], ingest=sink))
    assert sink.bindings[-1].stream == "demo:acct1"
    assert sink.bindings[-1].strict_schema is True


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.33")
def test_batch_size_commits_entities_then_edges_in_batches() -> None:
    mapped = Mapped()
    for n in range(5):
        mapped.entity(f"e{n}", "E")
    for n in range(1, 5):
        mapped.edge("e0", f"e{n}", "to")
    sink = _Ingest()
    stream = _stream(batch_size=2)
    assert _run(stream.mapped(mapped, ingest=sink)) == {"nodes": 5, "edges": 4}
    shapes = [(len(c.entities), len(c.relationships)) for c in sink.submitted]
    assert shapes == [(2, 0), (2, 0), (1, 0), (1, 2), (1, 2)]


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.35")
def test_ingest_tools_register_with_standard_annotations_and_run() -> None:
    clients: list[str] = []

    class Api:
        def close(self) -> None:
            clients.append("closed")

        def rows(self, limit: int = 10) -> list[dict[str, Any]]:
            return [{"id": str(n)} for n in range(limit)]

    def get_client() -> Api:
        return Api()

    def run(client: Api, limit: int = 3) -> list[dict[str, Any]]:
        """Ingest the first rows."""
        return client.rows(limit)

    def chain(client: Api, label: str) -> Mapped:
        return Mapped().entity(f"demo:{label}", "Chain")

    async def pages(
        client: Api, cursor: str | None, label: str
    ) -> list[dict[str, Any]]:
        offset = int(cursor or 0)
        return client.rows(4)[offset : offset + 2]

    sink = _Ingest()
    stream = _stream()
    from agent_connector_sdk.ingest import install_ingest

    install_ingest(sink)  # type: ignore[arg-type]
    try:
        register = ingest_registration(
            stream,
            [
                IngestTool("demo_ingest_rows", "Ingest rows", run, kind="row"),
                IngestTool("demo_ingest_chain", "Ingest chain", chain),
                IngestTool(
                    "demo_ingest_pages",
                    "Ingest pages",
                    pages,
                    kind="row",
                    paged=True,
                    strategy=OffsetCursor(2),
                ),
            ],
            get_client,
        )
        mcp = FastMCP("demo-mcp")
        register(mcp)

        async def main() -> None:
            async with Client(mcp) as client:
                tools = {t.name: t for t in await client.list_tools()}
                rows = tools["demo_ingest_rows"]
                assert tools["demo_ingest_rows"].meta["fastmcp"]["tags"] == sorted(
                    INGEST_TOOL_TAGS
                )
                assert rows.annotations.read_only_hint is False
                assert rows.annotations.idempotent_hint is True
                assert rows.annotations.title == "Ingest rows"
                assert "limit" in rows.input_schema["properties"]
                assert "client" not in rows.input_schema["properties"]
                assert rows.description == "Ingest the first rows."
                first = await client.call_tool("demo_ingest_rows", {"limit": 2})
                assert first.data == {"nodes": 2, "edges": 0}
                chained = await client.call_tool("demo_ingest_chain", {"label": "x"})
                assert chained.data == {"nodes": 1, "edges": 0}
                walked = await client.call_tool("demo_ingest_pages", {"label": "y"})
                assert walked.data == {"nodes": 4, "edges": 0}

        anyio.run(main)
    finally:
        install_ingest(None)
    assert clients == ["closed"] * 3


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.35")
def test_a_paged_tool_without_a_kind_is_refused() -> None:
    async def pages(client: Any, cursor: str | None) -> list[dict[str, Any]]:
        return []

    with pytest.raises(ValueError):
        ingest_registration(_stream(), [IngestTool("t", "T", pages, paged=True)], dict)


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.33")
def test_high_water_cursor_reads_only_changes_since_the_accepted_mark() -> None:
    mark = HighWaterCursor("rev")
    assert mark.first() is None
    assert mark.advance([{"rev": "2026-02"}, {"rev": "2026-03"}], None) == "2026-03"
    assert mark.advance([{"rev": "2026-01"}], "2026-03") == "2026-03"
    assert mark.advance([], "2026-03") is None
    data = [{"id": "a", "rev": "1"}, {"id": "b", "rev": "2"}]

    async def fetch(cursor: str | None) -> Any:
        return [r for r in data if cursor is None or r["rev"] > cursor]

    sink = _Ingest()
    assert _run(_stream().sync("row", fetch, strategy=mark, ingest=sink))["nodes"] == 2
    assert sink.cursor == "2"
    again = _Ingest(cursor="2")
    assert _run(_stream().sync("row", fetch, strategy=mark, ingest=again)) == {
        "nodes": 0,
        "edges": 0,
    }
