"""Web-fetch requests-floor: HTML -> markdown + OG metadata, via a local server."""

from __future__ import annotations

from agent_connector_sdk.adapters.web_fetch import (
    FetchedPage,
    extract_og_metadata,
    fetch_page,
)
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse

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
        page = await fetch_page(f"{server.base_url}/article")

    assert isinstance(page, FetchedPage)
    assert page.title == "A Normalized Page"
    assert page.description == "What this page is about"
    assert page.site_name == "Example Site"
    assert "Hello, world." in page.markdown
    assert page.backend == "requests"


async def test_fetch_page_returns_none_on_a_server_error() -> None:
    with ScriptedHttpServer(ScriptedResponse(status=503, body=b"nope")) as server:
        page = await fetch_page(f"{server.base_url}/down")

    assert page is None


async def test_fetch_page_returns_none_for_an_empty_body() -> None:
    with ScriptedHttpServer(ScriptedResponse(status=200, body=b"   ")) as server:
        page = await fetch_page(f"{server.base_url}/blank")

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
