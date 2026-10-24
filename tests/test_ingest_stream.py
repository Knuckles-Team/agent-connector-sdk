"""The SourceStream ingest entry: submit paths, paging and cursor checkpointing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anyio
import pytest

from agent_connector_sdk.ingest import (
    ChangeSet,
    FetchPage,
    IngestBinding,
    IngestError,
    Mapped,
    Mapper,
    RecordMap,
    SourceStream,
    open_client,
)

BINDING = IngestBinding(connector="demo-mcp", stream="demo")


class _Ingest:
    """Records submissions; the accepted cursor is the last one committed."""

    def __init__(self, cursor: str | None = None) -> None:
        self.cursor = cursor
        self.submitted: list[ChangeSet] = []

    async def submit(self, binding: IngestBinding, changes: ChangeSet) -> Any:
        assert binding is BINDING
        self.submitted.append(changes)
        self.cursor = changes.cursor or self.cursor
        return SimpleNamespace(
            affected_count=len(changes.entities) + len(changes.documents),
            relationship_count=len(changes.relationships),
        )

    async def accepted_cursor(self, binding: IngestBinding) -> str | None:
        return self.cursor


def _pair(records: Any) -> Mapped:
    return Mapped().entity("demo:a", "A").edge("demo:a", "demo:b", "to")


def _stream() -> SourceStream:
    pair: Mapper = _pair
    return SourceStream(
        BINDING,
        {
            "item": RecordMap("Item", "demo:item:{_id}", fields={"name": "name"}),
            "pair": pair,
        },
    )


def _run(coro: Any) -> Any:
    async def main() -> Any:
        return await coro

    return anyio.run(main)


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.31")
def test_entities_documents_and_kinds_return_counts() -> None:
    sink = _Ingest()
    stream = _stream()
    out = _run(
        stream.entities(
            [{"id": "1", "node_type": "T"}],
            [{"source": "1", "target": "2", "relationship": "r"}],
            ingest=sink,
        )
    )
    assert out == {"nodes": 1, "edges": 1}
    assert _run(stream.documents([{"id": "d", "text": "t"}], ingest=sink)) == {
        "nodes": 1,
        "edges": 0,
    }
    assert _run(stream.records("item", [{"id": "9", "name": "n"}], ingest=sink)) == {
        "nodes": 1,
        "edges": 0,
    }
    assert _run(stream.records("pair", [{}], ingest=sink)) == {"nodes": 1, "edges": 1}


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.31")
def test_empty_and_unknown_input_is_refused() -> None:
    sink = _Ingest()
    stream = _stream()
    for call in (
        stream.entities([], ingest=sink),
        stream.documents([], ingest=sink),
        stream.records("nope", [{"id": "1"}], ingest=sink),
        stream.records("item", [{"no": "id"}], ingest=sink),
    ):
        with pytest.raises(IngestError):
            _run(call)
    assert not sink.submitted


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.31")
def test_sync_pages_commit_each_cursor_and_resume() -> None:
    sink = _Ingest()
    stream = _stream()
    pages = {
        None: ([{"id": "1"}], "c1"),
        "c1": ([{"id": "2"}], "c2"),
        "c2": ([{"id": "3"}], None),
    }
    seen: list[str | None] = []

    async def fetch_impl(cursor: str | None) -> Any:
        seen.append(cursor)
        return pages[cursor]

    fetch: FetchPage = fetch_impl
    assert _run(stream.sync("item", fetch, ingest=sink)) == {"nodes": 3, "edges": 0}
    assert seen == [None, "c1", "c2"]
    assert [c.cursor for c in sink.submitted] == ["c1", "c2", None]

    sink = _Ingest(cursor="c2")
    seen.clear()
    assert _run(stream.sync("item", fetch, ingest=sink)) == {"nodes": 1, "edges": 0}
    assert seen == ["c2"]

    sink = _Ingest(cursor="c1")
    seen.clear()
    _run(stream.sync("item", fetch, ingest=sink, resume=False, max_pages=1))
    assert seen == [None]


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.31")
def test_open_client_closes_sync_and_async_clients() -> None:
    closed: list[str] = []

    class Sync:
        def close(self) -> None:
            closed.append("sync")

    class Async:
        async def aclose(self) -> None:
            closed.append("async")

    async def make_async() -> Any:
        return Async()

    async def main() -> None:
        async with open_client(Sync) as client:
            assert isinstance(client, Sync)
        async with open_client(make_async) as client:
            assert isinstance(client, Async)

    anyio.run(main)
    assert closed == ["sync", "async"]
