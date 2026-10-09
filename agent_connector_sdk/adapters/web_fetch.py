"""The requests-floor web-fetch backend: one URL fetched as markdown.

Ported from ``agent_utilities.knowledge_graph.ingestion.web_fetch``
(SDK-SOURCE-INGEST-R005) onto this SDK's own governed HTTP client
(:mod:`agent_connector_sdk.http.client`) instead of agent-utilities' bespoke
HTTP policy, since agent-utilities is not a dependency of this package.

This module ports only the zero-dependency ``requests`` floor: the HTTP GET,
Open Graph/Twitter Card metadata extraction, and markdown normalization. The
ArchiveBox and crawl4ai backends stay in agent-utilities for now (they call
back into agent-utilities-owned infrastructure: the MCP tool fleet and the
skill-graph crawler subprocess) and the ``ports.SourceAdapter`` wiring through
the generated SourceIngest client is a follow-up slice; both remain as open
lines in ``specs/SDK-SOURCE-INGEST/tasks.md``.
"""

from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, ConfigDict, Field

from agent_connector_sdk.http.client import create_async_http_client
from agent_connector_sdk.http.options import HttpClientOptions

__all__ = ["FetchedPage", "extract_og_metadata", "fetch_page"]

# Browser-like UA — the bare ``httpx`` agent is 403'd by many sites.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_META_ENTITY_RE = re.compile(r"&(#39|#x27|quot|apos|amp|lt|gt);")
_META_ENTITY_MAP = {
    "#39": "'",
    "#x27": "'",
    "quot": '"',
    "apos": "'",
    "lt": "<",
    "gt": ">",
    "amp": "&",  # decoded last so "&amp;lt;" does not double-unescape
}
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


class FetchedPage(BaseModel):
    """One fetched web page normalized to markdown/text, with provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    markdown: str
    title: str = ""
    backend: str = "requests"
    description: str = ""
    image: str = ""
    site_name: str = ""


def _decode_entities(text: str) -> str:
    return _META_ENTITY_RE.sub(lambda m: _META_ENTITY_MAP[m.group(1)], text)


def _meta_content(html: str, *patterns: str) -> str:
    """First non-empty ``<meta ... content="...">`` match across ``patterns``."""
    for key in patterns:
        for attr in ("property", "name"):
            for order in (
                rf'<meta[^>]+{attr}=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr}=["\']{re.escape(key)}["\']',
            ):
                m = re.search(order, html, re.IGNORECASE)
                if m and m.group(1).strip():
                    return _decode_entities(m.group(1).strip())
    return ""


def extract_og_metadata(html: str) -> dict[str, str]:
    """Open Graph / Twitter Card metadata from raw HTML.

    Zero-dependency (stdlib regex, no HTML parser); falls back across the OG,
    Twitter Card and plain ``description`` meta-tag families. ``""`` for any
    field not present.
    """
    return {
        "title": _meta_content(html, "og:title", "twitter:title"),
        "description": _meta_content(
            html, "og:description", "twitter:description", "description"
        ),
        "image": _meta_content(html, "og:image", "twitter:image"),
        "site_name": _meta_content(html, "og:site_name"),
    }


def _markdown_from_html(html: str) -> str:
    """A light tag strip: the zero-dependency text-normalization floor.

    The original agent-utilities backend also tries ``markitdown`` first and
    falls back to this same tag strip when it is absent; that richer HTML to
    markdown conversion is deferred to the next slice (see
    ``specs/SDK-SOURCE-INGEST/tasks.md``) rather than adding an unvetted,
    unpinned dependency to this port.
    """
    return _TAG_RE.sub(" ", html)


async def fetch_page(url: str, *, timeout: float = 30.0) -> FetchedPage | None:
    """Fetch ``url`` as markdown through the governed HTTP client.

    Returns ``None`` on a non-2xx response or empty content; a caller treats
    that as an unreachable source rather than a fabricated empty page.
    """
    options = HttpClientOptions(
        base_url=url, timeout=timeout, headers={"User-Agent": _USER_AGENT}
    )
    async with create_async_http_client(options) as client:
        try:
            response = await client.get("")
        except httpx.HTTPError:
            return None
    if response.status_code >= 400:
        return None
    raw = response.text
    text = _markdown_from_html(raw)
    if not text.strip():
        return None
    og = extract_og_metadata(raw)
    title_match = _TITLE_TAG_RE.search(raw)
    title = og["title"] or (title_match.group(1).strip() if title_match else "")
    return FetchedPage(
        url=url,
        markdown=text,
        title=title[:200],
        description=og["description"][:500],
        image=og["image"],
        site_name=og["site_name"],
    )
