"""Document-source connectors: registry gate, checkpoints, feeds and the HTTP boundary."""

from __future__ import annotations

import httpx
import pytest

from agent_connector_sdk.source_connectors import (
    ConnectorCheckpoint,
    ConnectorGovernanceError,
    LoadConnector,
    PollConnector,
    build_connector,
    list_sources,
)
from agent_connector_sdk.source_connectors.http_safety import (
    SourceEgressError,
    safe_get_text,
)
from agent_connector_sdk.source_connectors.registry import set_activation_gate

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
  <item><title>GPU</title><link>http://n/1</link><guid>http://n/1</guid>
    <pubDate>Tue, 17 Jun 2025 10:00:00 GMT</pubDate>
    <description>accelerator</description><category>hardware</category></item>
  <item><title>Round</title><link>http://n/2</link><guid>http://n/2</guid>
    <pubDate>Wed, 18 Jun 2025 10:00:00 GMT</pubDate>
    <description>Series B</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>arXiv</title>
  <entry><id>http://arxiv.org/abs/2601.00090v1</id>
    <title>Self-improving agents</title><summary>We study agents.</summary>
    <published>2026-01-02T09:00:00Z</published><updated>2026-01-02T09:00:00Z</updated>
    <author><name>A. Researcher</name></author><category term="cs.AI"/>
    <link href="http://arxiv.org/abs/2601.00090v1" rel="alternate"/>
    <link title="pdf" href="http://arxiv.org/pdf/2601.00090v1" rel="related"/>
  </entry>
</feed>"""


pytestmark = [
    pytest.mark.spec("SDK-SOURCE-INGEST-R800"),
    pytest.mark.spec("SDK-SOURCE-INGEST-R801"),
]


@pytest.fixture(autouse=True)
def _open_gate():
    set_activation_gate(lambda _source: True)
    yield
    set_activation_gate(None)


def test_registry_lists_builtin_sources_and_rejects_unknown():
    assert {"web", "rest", "rss", "arxiv"} <= set(list_sources())
    with pytest.raises(KeyError, match="Available"):
        build_connector("nope", {})


@pytest.mark.parametrize("gate", [None, lambda _source: False])
def test_activation_is_refused_without_a_certifying_gate(gate):
    set_activation_gate(gate)
    with pytest.raises(ConnectorGovernanceError, match="activation refused"):
        build_connector("rss", {"feed_urls": "http://f/"})


def test_checkpoint_round_trips_and_bad_input_is_none():
    cp = ConnectorCheckpoint(
        has_more=True, cursor="c", watermark="w", seen_ids=["a"], state={"k": 1}
    )
    assert ConnectorCheckpoint.from_json(cp.to_json()) == cp
    assert ConnectorCheckpoint.from_json(None) is None
    assert ConnectorCheckpoint.from_json("not-json") is None


def test_web_connector_crawls_to_depth_and_polls_incrementally():
    pages = {
        "http://x/": "<title>Home</title><a href='/a'>a</a>",
        "http://x/a": "<title>A</title>body",
    }
    conn = build_connector(
        "web", {"base_url": "http://x/", "max_depth": 1, "fetch_fn": pages.get}
    )
    assert {d.title for d in conn.load()} == {"Home", "A"}
    first = conn.poll()
    assert conn.poll(first.checkpoint).documents == []


def test_rest_connector_follows_cursor_and_refuses_cross_host_next_url():
    pages = {
        None: {"items": [{"id": 1, "title": "T1", "body": "x"}], "next": "c2"},
        "c2": {"items": [{"id": 2, "title": "T2", "body": "y"}], "next": None},
    }
    conn = build_connector(
        "rest",
        {
            "url": "http://api/",
            "records_field": "items",
            "text_field": "body",
            "cursor_field": "next",
            "cursor_param": "cursor",
            "fetch_fn": lambda url, params: pages[params.get("cursor")],
        },
    )
    assert [d.id for d in conn.load()] == ["1", "2"]

    hostile = build_connector(
        "rest",
        {
            "url": "https://api.example.invalid/items",
            "records_field": "items",
            "next_url_field": "next",
            "fetch_fn": lambda *_: {
                "items": [{"id": "one", "text": "b"}],
                "next": "http://127.0.0.1/private",
            },
        },
    )
    with pytest.raises(ValueError, match="egress policy"):
        list(hostile.load())


def test_rss_connector_parses_rss_and_atom_and_polls_by_watermark():
    feeds = {"http://f/rss": RSS, "http://f/atom": ATOM.replace("2601.00090v1", "x")}
    conn = build_connector("rss", {"feed_urls": list(feeds), "fetch_fn": feeds.get})
    assert isinstance(conn, LoadConnector | PollConnector)
    by_id = {d.id: d for d in conn.load()}
    rec = by_id["http://n/1"].metadata["record"]
    assert rec["categories"] == ["hardware"]
    assert rec["origin"]["streamId"] == "http://f/rss"

    single = build_connector(
        "rss", {"feed_urls": "http://f/rss", "fetch_fn": {"http://f/rss": RSS}.get}
    )
    batch = single.poll()
    assert len(batch.documents) == 2
    assert batch.checkpoint.watermark == "2025-06-18T10:00:00Z"
    assert single.poll(batch.checkpoint).documents == []


def _boom(*_args):
    raise RuntimeError("network down")


@pytest.mark.parametrize(
    ("kind", "config"),
    [("rss", {"feed_urls": "http://dead/"}), ("arxiv", {"categories": ["cs.AI"]})],
)
def test_dead_feed_never_aborts_a_sweep(kind, config):
    assert list(build_connector(kind, {**config, "fetch_fn": _boom}).load()) == []


def test_arxiv_connector_shapes_records_dedups_categories_and_polls():
    conn = build_connector(
        "arxiv",
        {"categories": ["cs.AI", "cs.LG"], "fetch_fn": lambda url, params: ATOM},
    )
    (doc,) = conn.load()
    rec = doc.metadata["record"]
    assert (doc.id, doc.doc_type) == ("arxiv:2601.00090", "paper")
    assert rec["authors"] == ["A. Researcher"]
    assert rec["pdf_url"] == "http://arxiv.org/pdf/2601.00090v1"
    batch = conn.poll()
    assert batch.checkpoint.watermark == "2026-01-02T09:00:00Z"
    assert conn.poll(batch.checkpoint).documents == []
    with pytest.raises(ValueError, match="categories"):
        build_connector("arxiv", {"fetch_fn": lambda *_: ATOM})


@pytest.mark.parametrize(
    ("location", "match"),
    [
        ("http://127.0.0.1/private", "egress policy"),
        ("http://public.example.invalid/clear", "downgrade"),
    ],
)
def test_http_boundary_revalidates_redirects(location, match):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": location}, request=request)

    with pytest.raises(SourceEgressError, match=match):
        safe_get_text(
            "https://public.example.invalid/start",
            transport=httpx.MockTransport(handler),
        )
    assert len(calls) == 1


def test_http_boundary_enforces_decoded_body_limit():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * 32, request=request)
    )
    with pytest.raises(SourceEgressError, match="configured limit"):
        safe_get_text(
            "https://public.example.invalid/d", transport=transport, max_bytes=8
        )
