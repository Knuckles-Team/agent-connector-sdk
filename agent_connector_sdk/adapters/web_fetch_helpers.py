"""Pure HTML metadata and text helpers for :mod:`agent_connector_sdk.adapters.web_fetch`."""

from __future__ import annotations

import re

from agent_connector_sdk.adapters.web_html_metadata import _extract_metadata
from agent_connector_sdk.adapters.web_html_text import _strip_tags

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


def _decode_entities(text: str) -> str:
    return _META_ENTITY_RE.sub(lambda m: _META_ENTITY_MAP[m.group(1)], text)


def extract_og_metadata(html: str) -> dict[str, str]:
    """Open Graph / Twitter Card metadata from raw HTML.

    Zero-dependency (stdlib regex, no HTML parser); falls back across the OG,
    Twitter Card and plain ``description`` meta-tag families. ``""`` for any
    field not present.
    """
    return _extract_metadata(html, _decode_entities)


def _markdown_from_html(html: str) -> str:
    """A light tag strip: the zero-dependency text-normalization floor.

    The original agent-utilities backend also tries ``markitdown`` first and
    falls back to this same tag strip when it is absent; that richer HTML to
    markdown conversion is deferred to the next slice (see
    ``specs/SCION-SOURCE-INGEST/tasks.md``) rather than adding an unvetted,
    unpinned dependency to this port.
    """
    return _strip_tags(html)
