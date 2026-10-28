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
    pytest.mark.spec("SDK-CONNECTOR-CONTROL-R014.5"),
    pytest.mark.spec("SDK-SOURCE-INGEST-R801"),
]


# spec: SDK-SOURCE-INGEST-R800.4
@pytest.mark.spec("SDK-SOURCE-INGEST-R800.1")
def test_registry_lists_builtin_sources_and_rejects_unknown():
    assert {"web", "rest", "rss", "arxiv"} <= set(list_sources())
    with pytest.raises(KeyError, match="Available"):
        build_connector("nope", {})


# spec: SDK-SOURCE-INGEST-R800.4
@pytest.mark.parametrize("gate", [None, lambda _source: False])
def test_activation_is_refused_without_a_certifying_gate(gate):
    set_activation_gate(gate)
    with pytest.raises(ConnectorGovernanceError, match="activation refused"):
        build_connector("rss", {"feed_urls": "http://f/"})


@pytest.mark.spec("SDK-SOURCE-INGEST-R800.5")
def test_checkpoint_round_trips_and_bad_input_is_none():
    cp = ConnectorCheckpoint(
        has_more=True, cursor="c", watermark="w", seen_ids=["a"], state={"k": 1}
    )
    assert ConnectorCheckpoint.from_json(cp.to_json()) == cp
    assert ConnectorCheckpoint.from_json(None) is None
    assert ConnectorCheckpoint.from_json("not-json") is None


@pytest.mark.spec("SDK-SOURCE-INGEST-R800.3")
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R800.9")
@pytest.mark.parametrize(
    "items",
    [
        None,
        {},
        ["bad"],
        [{"id": "", "body": "ok"}],
        [{"id": "x", "body": ""}],
        [{"id": "valid", "body": "ok"}, "bad"],
    ],
)
def test_rest_malformed_page_cannot_advance_checkpoint(items):
    prior = ConnectorCheckpoint(has_more=True, cursor="old")
    conn = build_connector(
        "rest",
        {
            "url": "http://api/",
            "records_field": "items",
            "text_field": "body",
            "cursor_field": "next",
            "cursor_param": "cursor",
            "fetch_fn": lambda *_: {"items": items, "next": "new"},
        },
    )
    with pytest.raises(ValueError, match="REST source"):
        conn.poll(prior)
    assert prior.cursor == "old"


@pytest.mark.spec("SDK-SOURCE-INGEST-R800.9")
def test_rest_empty_page_can_continue():
    conn = build_connector(
        "rest",
        {
            "url": "http://api/",
            "records_field": "items",
            "cursor_field": "next",
            "fetch_fn": lambda *_: {"items": [], "next": "new"},
        },
    )
    batch = conn.poll()
    assert batch.documents == []
    assert batch.checkpoint.cursor == "new"
    assert batch.checkpoint.has_more


@pytest.mark.spec("SDK-SOURCE-INGEST-R800.11")
@pytest.mark.parametrize("placement", ["top", "last_record"])
def test_rest_numeric_zero_cursor_is_followed(placement):
    requests = []

    def fetch(_url, params):
        requests.append(params.get("cursor"))
        if len(requests) == 1:
            if placement == "top":
                return {"items": [{"id": 1, "body": "one"}], "next": 0}
            return {"items": [{"id": 1, "body": "one", "next": 0}]}
        return {"items": [{"id": 2, "body": "two"}], "next": None}

    conn = build_connector(
        "rest",
        {
            "url": "http://api/",
            "records_field": "items",
            "text_field": "body",
            "cursor_field": "next",
            "cursor_param": "cursor",
            "fetch_fn": fetch,
        },
    )
    first = conn.poll()
    assert first.checkpoint.has_more
    assert first.checkpoint.cursor == "0"
    second = conn.poll(first.checkpoint)
    assert requests == [None, "0"]
    assert [doc.id for doc in second.documents] == ["2"]


# spec: SDK-SOURCE-INGEST-R800.2
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


# spec: SDK-SOURCE-INGEST-R800.2, SDK-SOURCE-INGEST-R800.6
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R800.8")
@pytest.mark.parametrize("failure", ["network", "malformed"])
def test_rss_partial_sweep_does_not_advance_watermark(failure):
    prior = ConnectorCheckpoint(watermark="2025-06-16T00:00:00Z")
    healthy = (
        RSS.replace("http://n/1", "http://n/3")
        .replace("http://n/2", "http://n/4")
        .replace("18 Jun 2025", "19 Jun 2025")
    )
    unavailable = True

    def fetch(url):
        if url == "https://feed.example/older" and unavailable:
            if failure == "network":
                raise RuntimeError("network down")
            return "<rss><broken>"
        return healthy if url.endswith("newer") else RSS

    conn = build_connector(
        "rss",
        {
            "feed_urls": ["https://feed.example/newer", "https://feed.example/older"],
            "fetch_fn": fetch,
        },
    )
    partial = conn.poll(prior)
    assert {doc.id for doc in partial.documents} == {"http://n/3", "http://n/4"}
    assert partial.checkpoint.watermark == prior.watermark
    unavailable = False
    recovered = conn.poll(partial.checkpoint)
    assert {doc.id for doc in recovered.documents} == {"http://n/1", "http://n/2"}
    assert recovered.checkpoint.watermark == "2025-06-19T10:00:00Z"


@pytest.mark.spec("SDK-SOURCE-INGEST-R800.7")
@pytest.mark.parametrize("failure", ["network", "malformed"])
def test_arxiv_partial_sweep_does_not_advance_watermark(failure):
    prior = ConnectorCheckpoint(watermark="2026-01-01T00:00:00Z")
    healthy = ATOM.replace("2601.00090", "2601.00091").replace(
        "2026-01-02T09:00:00Z", "2026-01-03T09:00:00Z"
    )
    unavailable = True

    def fetch(_url, params):
        if params["search_query"] == "cat:cs.LG" and unavailable:
            if failure == "network":
                raise RuntimeError("network down")
            return "<feed><broken>"
        return healthy if params["search_query"] == "cat:cs.AI" else ATOM

    conn = build_connector(
        "arxiv", {"categories": ["cs.AI", "cs.LG"], "fetch_fn": fetch}
    )
    partial = conn.poll(prior)
    assert [doc.id for doc in partial.documents] == ["arxiv:2601.00091"]
    assert partial.checkpoint.watermark == prior.watermark
    unavailable = False
    recovered = conn.poll(partial.checkpoint)
    assert [doc.id for doc in recovered.documents] == ["arxiv:2601.00090"]
    assert recovered.checkpoint.watermark == "2026-01-03T09:00:00Z"


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


# --- connector framework surface: typed documents, registration, drain loops ---

from agent_connector_sdk.source_connectors import (  # noqa: E402
    BaseSourceConnector,
    CheckpointedBatch,
    PermSyncConnector,
    SlimConnector,
    SlimDocument,
    SourceDocument,
    get_connector_class,
    register_source,
)
from agent_connector_sdk.source_connectors.base import ExternalAccess  # noqa: E402
from agent_connector_sdk.source_connectors.connectors.arxiv import (  # noqa: E402
    ArxivConnector,
)
from agent_connector_sdk.source_connectors.connectors.package_manifest import (  # noqa: E402
    ONYX_CONNECTOR_PARITY,
    PACKAGE_PRESETS,
    get_preset,
    list_presets,
    onyx_parity,
    onyx_parity_summary,
)
from agent_connector_sdk.source_connectors.connectors.rest import (  # noqa: E402
    RestJsonConnector,
)
from agent_connector_sdk.source_connectors.connectors.rss import (  # noqa: E402
    RssConnector,
)
from agent_connector_sdk.source_connectors.connectors.web import (  # noqa: E402
    WebCrawlerConnector,
)
from agent_connector_sdk.source_connectors.http_safety import (  # noqa: E402
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MAX_REQUEST_BYTES,
    HARD_MAX_REDIRECTS,
    HARD_MAX_RESPONSE_BYTES,
    ResolvedSourceURL,
    configured_source_http_policy,
    normalize_allowed_hosts,
    require_safe_source_url,
    resolve_safe_source_url,
    safe_delete_json,
    safe_get_bytes,
    safe_get_bytes_async,
    safe_get_json,
    safe_get_json_async,
    safe_get_text_async,
    safe_post_json_async,
    source_url_host,
)


def test_builtin_sources_resolve_to_their_connector_classes():
    expected = {
        "web": WebCrawlerConnector,
        "rest": RestJsonConnector,
        "rss": RssConnector,
        "arxiv": ArxivConnector,
    }
    for source_type, cls in expected.items():
        assert get_connector_class(source_type) is cls
        assert issubclass(cls, BaseSourceConnector)
        assert cls.source_type == source_type
    assert get_connector_class("not-a-source") is None


def test_register_source_binds_key_and_drain_loop_follows_has_more():
    @register_source("test-paged")
    class _Paged(PollConnector):
        def poll(self, checkpoint=None):
            page = int(checkpoint.cursor) if checkpoint and checkpoint.cursor else 0
            return CheckpointedBatch(
                documents=[SourceDocument(id=f"d{page}", text="t")],
                checkpoint=ConnectorCheckpoint(has_more=page < 2, cursor=str(page + 1)),
            )

    assert _Paged.source_type == "test-paged"
    assert get_connector_class("test-paged") is _Paged
    conn = build_connector("test-paged", {})
    assert [d.id for d in conn.poll_all()] == ["d0", "d1", "d2"]
    assert conn.last_checkpoint is not None and conn.last_checkpoint.has_more is False
    with pytest.raises(TypeError, match="BaseSourceConnector"):
        register_source("bad")(object)  # type: ignore[type-var]


def test_slim_and_perm_sync_connectors_enumerate_ids_and_access():
    class _Perm(PermSyncConnector):
        def slim(self):
            yield SlimDocument(id="a", source_uri="s://a")

        def fetch_access(self):
            yield "a", ExternalAccess.public()

    conn = _Perm()
    assert isinstance(conn, SlimConnector)
    assert [d.id for d in conn.slim()] == ["a"]
    ((doc_id, access),) = list(conn.fetch_access())
    assert doc_id == "a" and access == ExternalAccess.public()
    with pytest.raises(TypeError):
        SlimConnector()  # type: ignore[abstract]


def test_package_presets_and_onyx_parity_catalog():
    assert list_presets() == sorted(PACKAGE_PRESETS)
    first = list_presets()[0]
    assert get_preset(first) == PACKAGE_PRESETS[first]
    assert get_preset(first.split("-")[0]) == PACKAGE_PRESETS[first]
    assert get_preset("definitely-missing") == {}
    assert onyx_parity("GitHub") == ONYX_CONNECTOR_PARITY["github"]
    assert onyx_parity("unknown") is None
    summary = onyx_parity_summary()
    assert summary["onyx_sources_mapped"] == len(ONYX_CONNECTOR_PARITY)
    assert sum(summary["by_route"].values()) == len(ONYX_CONNECTOR_PARITY)
    assert "github-agent" in summary["native_packages"]


def _resolver(*addresses):
    return lambda host, port: [(0, 0, 0, "", (ip, 0)) for ip in addresses]


def test_url_policy_resolves_once_and_denies_private_answers():
    resolved = resolve_safe_source_url(
        "https://Public.Example.com/x", resolver=_resolver("93.184.216.34")
    )
    assert isinstance(resolved, ResolvedSourceURL)
    assert (resolved.host, resolved.scheme) == ("public.example.com", "https")
    assert resolved.pinned_ip == "93.184.216.34"
    with pytest.raises(SourceEgressError):
        resolve_safe_source_url(
            "https://rebind.example.com/", resolver=_resolver("10.0.0.5")
        )
    assert (
        require_safe_source_url("https://public.example.com/", resolve_dns=False)
        == "public.example.com"
    )
    assert source_url_host("https://Public.Example.com:8443/p") == "public.example.com"
    with pytest.raises(SourceEgressError):
        source_url_host("http://127.0.0.1/")
    assert normalize_allowed_hosts([" Intranet.Local. ", ""]) == frozenset(
        {"intranet.local"}
    )
    with pytest.raises(SourceEgressError, match="exact hostnames"):
        normalize_allowed_hosts(["*.corp"])


def test_bounded_limits_and_operator_policy(monkeypatch):
    assert DEFAULT_MAX_REDIRECTS <= HARD_MAX_REDIRECTS
    assert DEFAULT_MAX_REQUEST_BYTES <= HARD_MAX_RESPONSE_BYTES
    with pytest.raises(ValueError, match="max_redirects"):
        safe_get_bytes(
            "https://public.example.invalid/", max_redirects=HARD_MAX_REDIRECTS + 1
        )
    with pytest.raises(ValueError, match="max_bytes"):
        safe_get_bytes(
            "https://public.example.invalid/", max_bytes=HARD_MAX_RESPONSE_BYTES + 1
        )
    policy = configured_source_http_policy()
    assert policy["max_redirects"] == DEFAULT_MAX_REDIRECTS
    assert set(policy) == {
        "max_bytes",
        "max_redirects",
        "allowed_private_hosts",
        "allowed_redirect_hosts",
    }


def _json_transport(calls, body=b'{"ok": true}'):
    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "application/json"},
            request=request,
        )

    return httpx.MockTransport(handler)


def test_json_reads_and_writes_go_through_the_bounded_boundary():
    calls: list[httpx.Request] = []
    transport = _json_transport(calls)
    assert safe_get_json("https://public.example.invalid/j", transport=transport) == {
        "ok": True
    }
    assert safe_delete_json(
        "https://public.example.invalid/j/1", transport=transport
    ) == {"ok": True}
    assert [c.method for c in calls] == ["GET", "DELETE"]
    with pytest.raises(SourceEgressError, match="valid JSON"):
        safe_get_json(
            "https://public.example.invalid/j", transport=_json_transport([], b"nope")
        )


async def test_async_boundary_reads_text_json_bytes_and_posts():
    calls: list[httpx.Request] = []
    transport = _json_transport(calls)
    url = "https://public.example.invalid/a"
    body, _ = await safe_get_bytes_async(url, transport=transport)
    assert body == b'{"ok": true}'
    assert await safe_get_text_async(url, transport=transport) == '{"ok": true}'
    assert await safe_get_json_async(url, transport=transport) == {"ok": True}
    assert await safe_post_json_async(url, {"x": 1}, transport=transport) == {
        "ok": True
    }
    assert calls[-1].method == "POST" and calls[-1].content == b'{"x":1}'
