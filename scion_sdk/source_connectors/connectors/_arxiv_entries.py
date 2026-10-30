"""Entry-to-document shaping for the native arXiv connector."""

from __future__ import annotations

from typing import Any

from ..base import ExternalAccess, SourceDocument
from ._feed_common import _entry_categories, _entry_date


def _arxiv_bare_id(raw_id: str) -> str:
    """Strip the ``https://arxiv.org/abs/`` prefix and version suffix from an entry id."""
    tail = str(raw_id or "").rsplit("/", 1)[-1]
    if "v" in tail:
        head, _, version = tail.rpartition("v")
        if version.isdigit():
            tail = head
    return tail


def _pdf_url(entry: dict[str, Any]) -> str:
    for link in entry.get("links") or []:
        if not isinstance(link, dict):
            continue
        if link.get("type") == "application/pdf" or link.get("title") == "pdf":
            return str(link.get("href") or "")
    return ""


def _authors(entry: dict[str, Any]) -> list[str]:
    out = []
    for author in entry.get("authors") or []:
        name = author.get("name") if isinstance(author, dict) else None
        if name:
            out.append(str(name))
    return out


def _entry_record(
    entry: dict[str, Any], aid: str, abs_url: str, category: str
) -> dict[str, Any]:
    return {
        "id": aid,
        "title": str(entry.get("title") or "").strip(),
        "published": _entry_date(entry),
        "categories": _entry_categories(entry) or [category],
        "authors": _authors(entry),
        "pdf_url": _pdf_url(entry),
        "canonical": [{"href": abs_url}],
        "origin": {
            "htmlUrl": abs_url,
            "streamId": "arxiv:api",
            "title": f"arXiv {category}",
        },
    }


def _entry_document(
    entry: dict[str, Any],
    *,
    category: str,
    doc_type: str,
    source_name: str,
    external_access: ExternalAccess,
) -> SourceDocument | None:
    """Shape one Atom entry into a ``SourceDocument`` (``None`` when it has no id)."""
    raw_id = str(entry.get("id") or "")
    aid = _arxiv_bare_id(raw_id)
    if not aid:
        return None
    abs_url = raw_id or f"https://arxiv.org/abs/{aid}"
    record = _entry_record(entry, aid, abs_url, category)
    return SourceDocument(
        id=f"arxiv:{aid}",
        source_uri=abs_url,
        title=record["title"][:300],
        text=str(entry.get("summary") or "").strip(),
        doc_type=doc_type,
        updated_at=record["published"],
        metadata={"record": record, "source_system": source_name},
        external_access=external_access.model_copy(deep=True),
    )
