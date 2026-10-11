"""Pure HTML metadata and text helpers for :mod:`agent_connector_sdk.adapters.web_fetch`."""

from __future__ import annotations

import re

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
_TAG_RE = re.compile(r"<[^>]+>")


def _decode_entities(text: str) -> str:
    return _META_ENTITY_RE.sub(lambda m: _META_ENTITY_MAP[m.group(1)], text)


def _meta_patterns(key: str) -> tuple[str, ...]:
    """Every ``<meta>`` regex variant (attr x attribute order) for ``key``."""
    patterns: list[str] = []
    for attr in ("property", "name"):
        patterns.append(
            rf'<meta[^>]+{attr}=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']'
        )
        patterns.append(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr}=["\']{re.escape(key)}["\']'
        )
    return tuple(patterns)


def _meta_content(html: str, *patterns: str) -> str:
    """First non-empty ``<meta ... content="...">`` match across ``patterns``."""
    for key in patterns:
        for order in _meta_patterns(key):
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
