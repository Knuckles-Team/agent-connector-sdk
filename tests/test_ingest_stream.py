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
    IngestUnavailableError,
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
        self.bindings: list[IngestBinding] = []

    async def submit(self, binding: IngestBinding, changes: ChangeSet) -> Any:
        self.bindings.append(binding)
        self.submitted.append(changes)
        self.cursor = changes.cursor or self.cursor
        return SimpleNamespace(
            affected_count=len(changes.entities)
            + len(changes.documents)
            + len(changes.media),
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


class _Refusing(_Ingest):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def submit(self, binding: IngestBinding, changes: ChangeSet) -> Any:
        raise self.error


DOCS = IngestBinding(connector="demo-mcp", stream="demo-documents")


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.32")
def test_best_effort_never_raises_and_drops_incomplete_records() -> None:
    stream = SourceStream(
        BINDING, {"item": RecordMap("Item", "x:{_id}")}, best_effort=True
    )
    sink = _Ingest()
    assert _run(stream.entities([], ingest=sink)) is None
    assert _run(stream.documents([{"id": "d"}], ingest=sink)) is None
    assert _run(stream.records("nope", [{"id": "1"}], ingest=sink)) is None
    assert _run(stream.media(b"", "image/png", ingest=sink)) is None
    assert not sink.submitted
    out = _run(
        stream.entities(
            [{"id": "1", "node_type": "T"}, {"node_type": "T"}], ingest=sink
        )
    )
    assert out == {"nodes": 1, "edges": 0}
    assert len(sink.submitted[0].entities) == 1
    for error in (IngestError("refused"), IngestUnavailableError("down")):
        bad = _Refusing(error)
        assert (
            _run(stream.entities([{"id": "1", "node_type": "T"}], ingest=bad)) is None
        )
    strict = SourceStream(BINDING)
    with pytest.raises(IngestError):
        _run(
            strict.entities(
                [{"id": "1", "node_type": "T"}], ingest=_Refusing(IngestError("x"))
            )
        )


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.32")
def test_documents_land_in_their_own_stream_when_declared() -> None:
    stream = SourceStream(
        BINDING,
        {"mixed": lambda records: Mapped().entity("e", "E").document("d", "text")},
        document_binding=DOCS,
    )
    sink = _Ingest()
    _run(stream.documents([{"id": "d", "text": "t"}], ingest=sink))
    _run(stream.entities([{"id": "e", "node_type": "E"}], ingest=sink))
    assert sink.bindings == [DOCS, BINDING]
    sink = _Ingest()
    assert _run(stream.records("mixed", [{}], ingest=sink)) == {"nodes": 2, "edges": 0}
    assert sink.bindings == [BINDING, DOCS]
    assert not sink.submitted[0].documents and sink.submitted[1].documents


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.32")
def test_batch_media_and_raw_submit_share_one_path() -> None:
    stream = _stream()
    sink = _Ingest()
    out = _run(
        stream.batch(
            [{"id": "e", "node_type": "E"}],
            [{"source": "e", "target": "d", "relationship": "r"}],
            [{"id": "d", "text": "t"}],
            ingest=sink,
        )
    )
    assert out == {"nodes": 2, "edges": 1}
    assert len(sink.submitted) == 1
    assert _run(stream.media(b"png", "image/png", name="a.png", ingest=sink)) == {
        "nodes": 1,
        "edges": 0,
    }
    assert sink.submitted[-1].media[0].name == "a.png"
    with pytest.raises(IngestError):
        _run(stream.media(b"", "image/png", ingest=sink))
    other = IngestBinding(connector="demo-mcp", stream="other")
    _run(stream.submit(ChangeSet(), binding=other, ingest=sink))
    assert sink.bindings[-1] is other


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.46")
def test_sync_refuses_split_document_pages_before_any_submission() -> None:
    sink = _Ingest(cursor="old")

    async def fetch(cursor):
        assert cursor == "old"
        return [{}], "next"

    for mapper in (
        lambda records: Mapped().entity("e", "E").document("d", "text"),
        lambda records: Mapped().document("d", "text"),
    ):
        stream = SourceStream(BINDING, {"item": mapper}, document_binding=DOCS)
        with pytest.raises(IngestError, match="split document streams"):
            _run(stream.sync("item", fetch, ingest=sink))
        assert sink.submitted == []
        assert sink.cursor == "old"

    # A separate document binding does not block entity-only sync.
    stream = SourceStream(
        BINDING,
        {"item": lambda records: Mapped().entity("e", "E")},
        document_binding=DOCS,
    )
    assert _run(stream.sync("item", fetch, ingest=sink, max_pages=1)) == {
        "nodes": 1,
        "edges": 0,
    }
    assert sink.cursor == "next"
