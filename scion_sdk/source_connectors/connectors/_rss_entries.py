"""Feed parsing and entry shaping for the native RSS/Atom connector."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..base import SourceDocument
from ..http_safety import safe_get_text
from ._feed_common import _entry_categories, _entry_date

FetchFn = Callable[[str], str]
#: Per-feed HTTP fetch timeout (seconds).
_FEED_FETCH_TIMEOUT_S = 20.0


def _parse_feed(content: str) -> Any:
    """Parse feed content with lazy ``feedparser``."""
    try:
        import feedparser
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise RuntimeError(
            "RssConnector needs 'feedparser' to parse feeds (declared in "
            "pyproject dependencies)."
        ) from exc
    return feedparser.parse(content)


def _entry_text(entry: Any) -> str:
    content = entry.get("content")
    if isinstance(content, list) and content:
        val = content[0].get("value") if isinstance(content[0], dict) else None
        if val:
            return str(val)
    return str(entry.get("summary") or entry.get("description") or "")


def _normalize_feed_urls(feed_urls: list[str] | str | tuple[str, ...]) -> list[str]:
    urls = [feed_urls] if isinstance(feed_urls, str) else list(feed_urls or [])
    cleaned = [u for u in (s.strip() for s in urls) if u]
    if not cleaned:
        raise ValueError("RssConnector requires one or more 'feed_urls'")
    if len(cleaned) > 1000:
        raise ValueError("RssConnector accepts at most 1000 feed URLs")
    return cleaned


def _build_safe_fetch(
    *,
    allowed_private_hosts: list[str],
    allowed_redirect_hosts: list[str],
    max_response_bytes: int,
) -> FetchFn:
    def _safe_fetch(url: str) -> str:
        return safe_get_text(
            url,
            timeout=_FEED_FETCH_TIMEOUT_S,
            headers={"User-Agent": "agent-utilities-rss/1.0"},
            max_bytes=max_response_bytes,
            allowed_private_hosts=allowed_private_hosts,
            allowed_redirect_hosts=allowed_redirect_hosts,
        )

    return _safe_fetch


def _entry_document(
    entry: Any,
    *,
    url: str,
    feed_title: str,
    doc_type: str,
    source_name: str,
    external_access: Any,
) -> SourceDocument | None:
    eid = entry.get("id") or entry.get("link") or entry.get("title") or ""
    if not eid:
        return None
    published = _entry_date(entry)
    link = str(entry.get("link") or "")
    title = str(entry.get("title") or "")
    record = {
        "id": str(eid),
        "title": title,
        "published": published,
        "categories": _entry_categories(entry),
        # ``canonical`` + ``origin`` mirror the GReader shape the gate reads,
        # so RssConnector items route through the SAME router as FreshRSS.
        "canonical": [{"href": link}] if link else [],
        "origin": {"htmlUrl": link, "streamId": url, "title": feed_title},
    }
    return SourceDocument(
        id=str(eid),
        source_uri=url,
        title=title[:300],
        text=_entry_text(entry),
        doc_type=doc_type,
        updated_at=published,
        metadata={"record": record, "source_system": source_name},
        external_access=external_access.model_copy(deep=True),
    )
