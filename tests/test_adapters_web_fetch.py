"""Web-fetch requests-floor: HTML -> markdown + OG metadata, via a local server."""

from __future__ import annotations

import socket

import httpx
import pytest

from scion_sdk.adapters.web_fetch import (
    FetchedPage,
    extract_og_metadata,
    fetch_page,
)
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse

_HTML = b"""
<html>
<head>
<title>Fallback Title</title>
<meta property="og:title" content="A Normalized Page" />
<meta property="og:description" content="What this page is about" />
<meta property="og:image" content="https://example.invalid/preview.png" />
<meta property="og:site_name" content="Example Site" />
</head>
<body><p>Hello, world.</p></body>
</html>
"""


async def test_fetch_page_normalizes_markdown_and_og_metadata() -> None:
    with ScriptedHttpServer(
        ScriptedResponse(status=200, body=_HTML, headers={"Content-Type": "text/html"})
    ) as server:
        page = await fetch_page(
            f"{server.base_url}/article", allowed_private_hosts=("127.0.0.1",)
        )

    assert isinstance(page, FetchedPage)
    assert page.title == "A Normalized Page"
    assert page.description == "What this page is about"
    assert page.site_name == "Example Site"
    assert "Hello, world." in page.markdown
    assert page.backend == "requests"


async def test_fetch_page_returns_none_on_a_server_error() -> None:
    with ScriptedHttpServer(ScriptedResponse(status=503, body=b"nope")) as server:
        page = await fetch_page(
            f"{server.base_url}/down", allowed_private_hosts=("127.0.0.1",)
        )

    assert page is None


async def test_fetch_page_returns_none_for_an_empty_body() -> None:
    with ScriptedHttpServer(ScriptedResponse(status=200, body=b"   ")) as server:
        page = await fetch_page(
            f"{server.base_url}/blank", allowed_private_hosts=("127.0.0.1",)
        )

    assert page is None


def test_og_metadata_falls_back_to_twitter_card_and_description() -> None:
    html = (
        '<meta name="twitter:title" content="Twitter Title">'
        '<meta name="description" content="Plain description">'
    )
    metadata = extract_og_metadata(html)

    assert metadata["title"] == "Twitter Title"
    assert metadata["description"] == "Plain description"
    assert metadata["image"] == ""


def test_og_metadata_decodes_html_entities() -> None:
    html = '<meta property="og:title" content="Rock &amp; Roll&#39;s Best">'
    metadata = extract_og_metadata(html)

    assert metadata["title"] == "Rock & Roll's Best"


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.42")
async def test_fetch_rejects_loopback_without_explicit_allowlist() -> None:
    with ScriptedHttpServer(ScriptedResponse(body=_HTML)) as server:
        assert await fetch_page(server.base_url) is None
        assert server.requests == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.42")
async def test_fetch_rejects_public_hostname_resolving_to_private(monkeypatch) -> None:
    from scion_sdk.adapters import web_fetch
    from scion_sdk.http.client import create_async_http_client

    seen: list[httpx.Request] = []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    transport = httpx.MockTransport(
        lambda request: seen.append(request) or httpx.Response(200, content=_HTML)
    )
    monkeypatch.setattr(
        web_fetch,
        "create_async_http_client",
        lambda options: create_async_http_client(options, transport=transport),
    )
    assert await fetch_page("https://public.example/article") is None
    assert seen == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.42")
async def test_explicit_private_host_allowlist_permits_local_fetch() -> None:
    with ScriptedHttpServer(ScriptedResponse(body=_HTML)) as server:
        page = await fetch_page(server.base_url, allowed_private_hosts=("127.0.0.1",))
        assert isinstance(page, FetchedPage)
        assert len(server.requests) == 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.48")
async def test_legacy_fetch_stops_on_oversized_or_compressed_response(
    monkeypatch,
) -> None:
    from scion_sdk.adapters import web_fetch
    from scion_sdk.http.client import create_async_http_client

    class Chunks(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.reads = 0
            self.closed = False

        async def __aiter__(self):
            for part in (b"12345", b"67890", b"remaining"):
                self.reads += 1
                yield part

        async def aclose(self) -> None:
            self.closed = True

    class Peer:
        def get_extra_info(self, name):
            return ("127.0.0.1", 80) if name == "server_addr" else None

    streams = []
    encoding = ["identity"]
    declared = [None]

    def respond(request):
        assert request.headers["accept-encoding"] == "identity"
        stream = Chunks()
        streams.append(stream)
        headers = {"content-encoding": encoding[0]}
        if declared[0] is not None:
            headers["content-length"] = declared[0]
        return httpx.Response(
            200, headers=headers, stream=stream, extensions={"network_stream": Peer()}
        )

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(web_fetch, "DEFAULT_MAX_RESPONSE_BYTES", 8)
    monkeypatch.setattr(
        web_fetch,
        "create_async_http_client",
        lambda options: create_async_http_client(options, transport=transport),
    )
    url = "http://127.0.0.1/article"
    assert await fetch_page(url, allowed_private_hosts=("127.0.0.1",)) is None
    assert streams[-1].reads == 2 and streams[-1].closed
    declared[0] = "9"
    assert await fetch_page(url, allowed_private_hosts=("127.0.0.1",)) is None
    assert streams[-1].reads == 0 and streams[-1].closed
    declared[0] = None
    encoding[0] = "gzip"
    assert await fetch_page(url, allowed_private_hosts=("127.0.0.1",)) is None
    assert streams[-1].reads == 0 and streams[-1].closed


@pytest.mark.timeout(10)
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.51")
def test_legacy_tag_strip_handles_unclosed_input() -> None:
    import random
    import re

    from scion_sdk.adapters.web_fetch_helpers import _markdown_from_html

    rng = random.Random(21)
    for _ in range(1000):
        text = "".join(rng.choice("<>abc ") for _ in range(rng.randrange(80)))
        assert _markdown_from_html(text) == re.sub(r"<[^>]+>", " ", text)
    unclosed = "<" * 400_000
    assert _markdown_from_html(unclosed) == unclosed


@pytest.mark.timeout(30)
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.52")
def test_metadata_scanning_is_linear_on_unclosed_tags() -> None:
    import random
    import re

    from scion_sdk.adapters.web_fetch_helpers import _decode_entities

    def old_title(html: str) -> str:
        for key in ("og:title", "twitter:title"):
            for attr in ("property", "name"):
                patterns = (
                    rf"""<meta[^>]+{attr}=["']{key}["'][^>]+content=["']([^"']+)["'][^>]*>""",
                    rf"""<meta[^>]+content=["']([^"']+)["'][^>]+{attr}=["']{key}["'][^>]*>""",
                )
                for pattern in patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match and match.group(1).strip():
                        return _decode_entities(match.group(1).strip())
        return ""

    rng = random.Random(52)
    choices = (
        'property="og:title"',
        'name="og:title"',
        'property="twitter:title"',
        'content="one"',
        'content="Rock &amp; Roll"',
        'content="two"',
        'content="  "',
        'name="unused"',
        'content="a>b"',
        'data="a>b"',
        "PROPERTY='OG:TITLE'",
        "NAME='TWITTER:TITLE'",
        "CONTENT='single quote'",
    )
    for _ in range(1000):
        tags = [
            "<meta "
            + " ".join(rng.choice(choices) for _ in range(rng.randrange(1, 7)))
            + ">"
            for _ in range(rng.randrange(1, 5))
        ]
        html = "".join(tags)
        assert extract_og_metadata(html)["title"] == old_title(html)
    assert (
        extract_og_metadata('<meta property="og:title" content="A &amp; B">')["title"]
        == "A & B"
    )
    assert extract_og_metadata("<meta " * 100_000)["title"] == ""
    assert extract_og_metadata("<meta " * 100_000 + ">")["title"] == ""
    assert (
        extract_og_metadata("<meta " + 'property="og:title" ' * 20_000 + ">")["title"]
        == ""
    )


@pytest.mark.timeout(10)
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.53")
def test_title_scanning_is_linear_and_matches_prior_behavior() -> None:
    import random
    import re

    from scion_sdk.adapters.web_html_text import _title_from_html

    old = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
    rng = random.Random(53)
    tokens = ("<title", ">", "</title>", "<TITLE>", "text", "\n", " ", "<x>")
    for _ in range(1000):
        html = "".join(rng.choice(tokens) for _ in range(rng.randrange(30)))
        match = old.search(html)
        assert _title_from_html(html) == (match.group(1).strip() if match else "")
    assert _title_from_html("<title " * 100_000) == ""
    assert _title_from_html("<title>" * 100_000) == ""
