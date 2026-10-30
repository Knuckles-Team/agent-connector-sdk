"""Bounded incremental web crawl and resumption."""

from __future__ import annotations

import pytest

from agent_connector_sdk.source_connectors import ConnectorCheckpoint, build_connector


@pytest.mark.spec("SCION-SOURCE-INGEST-R800.10")
def test_web_poll_bounds_fetches_and_resumes_frontier():
    pages = {
        "https://example.org/": '<title>Root</title><a href="/a">a</a>',
        "https://example.org/a": '<title>A</title><a href="/b">b</a>',
        "https://example.org/b": "<title>B</title><p>Text</p>",
    }
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    conn = build_connector(
        "web",
        {
            "base_url": "https://example.org/",
            "max_depth": 2,
            "max_pages": 1,
            "fetch_fn": fetch,
        },
    )
    checkpoint = ConnectorCheckpoint(seen_ids=["https://example.org/"])
    batches = []
    while True:
        before = len(calls)
        batch = conn.poll(checkpoint)
        assert len(calls) - before <= 1
        batches.extend(doc.id for doc in batch.documents)
        checkpoint = ConnectorCheckpoint.from_json(batch.checkpoint.to_json())
        assert checkpoint is not None
        if not checkpoint.has_more:
            break
    assert calls == list(pages)
    assert batches == ["https://example.org/a", "https://example.org/b"]
    before = len(calls)
    repeated = conn.poll(checkpoint)
    assert len(calls) - before == 1
    assert repeated.documents == []
    assert repeated.checkpoint.has_more


@pytest.mark.spec("SCION-SOURCE-INGEST-R800.10")
def test_web_poll_refuses_wrong_source_frontier_before_fetch():
    calls = []
    conn = build_connector(
        "web",
        {"base_url": "https://example.org/", "max_pages": 1, "fetch_fn": calls.append},
    )
    bad = ConnectorCheckpoint(
        has_more=True, state={"base_url": "https://elsewhere.invalid/"}
    )
    with pytest.raises(ValueError, match="checkpoint"):
        conn.poll(bad)
    assert calls == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R800.10")
def test_web_frontier_overflow_refuses_without_checkpoint(monkeypatch):
    monkeypatch.setattr(
        "agent_connector_sdk.source_connectors.connectors.web_frontier._FRONTIER_LIMIT",
        1,
    )
    conn = build_connector(
        "web",
        {
            "base_url": "https://example.org/",
            "max_pages": 1,
            "fetch_fn": lambda _url: '<a href="/a">a</a><a href="/b">b</a>',
        },
    )
    with pytest.raises(ValueError, match="frontier"):
        conn.poll()


@pytest.mark.spec("SCION-SOURCE-INGEST-R800.10")
def test_web_frontier_refuses_unsafe_url_before_fetch():
    calls = []
    conn = build_connector(
        "web",
        {
            "base_url": "https://example.org/",
            "same_domain": False,
            "fetch_fn": calls.append,
        },
    )
    checkpoint = ConnectorCheckpoint(
        has_more=True,
        state={
            "base_url": "https://example.org/",
            "max_depth": 1,
            "same_domain": False,
            "queue": [["http://127.0.0.1/private", 1]],
            "visited": ["https://example.org/"],
        },
    )
    with pytest.raises(ValueError, match="checkpoint"):
        conn.poll(checkpoint)
    assert calls == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R800.10")
def test_web_load_budget_counts_empty_pages():
    calls = []

    def fetch(url):
        calls.append(url)
        return '<a href="/a"></a>'

    conn = build_connector(
        "web", {"base_url": "https://example.org/", "max_pages": 1, "fetch_fn": fetch}
    )
    assert list(conn.load()) == []
    assert calls == ["https://example.org/"]
