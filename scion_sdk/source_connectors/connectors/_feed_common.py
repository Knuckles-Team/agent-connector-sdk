"""Helpers shared by the feed-style connectors (``rss`` and ``arxiv``)."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from ..base import CheckpointedBatch, ConnectorCheckpoint, SourceDocument

#: Cap the persisted seen-id belt so the checkpoint can't grow unbounded; the
#: publish-date watermark is the primary delta, seen_ids only guards same-date dupes.
_SEEN_CAP = 5000
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_DATE_KEYS = ("published_parsed", "updated_parsed")


def _format_date(parsed: Any) -> str | None:
    try:
        return time.strftime(_DATE_FORMAT, parsed)
    except (TypeError, ValueError):
        return None


def _entry_date(entry: Any) -> str | None:
    """Normalize an entry's publish/updated date to an ISO-8601 UTC string.

    ISO-8601 sorts lexicographically == chronologically, so the connector's
    watermark comparison is a plain string compare.
    """
    for key in _DATE_KEYS:
        parsed = entry.get(key)
        if not parsed:
            continue
        formatted = _format_date(parsed)
        if formatted is not None:
            return formatted
    return None


def _entry_categories(entry: Any) -> list[str]:
    """Return the non-empty ``term`` of every tag dict on a feed entry."""
    return [
        str(t.get("term"))
        for t in (entry.get("tags") or [])
        if isinstance(t, dict) and t.get("term")
    ]


def _is_fresh(doc: SourceDocument, prior_ids: set[str], wm: str | None) -> bool:
    return doc.id not in prior_ids and (
        wm is None or not doc.updated_at or doc.updated_at >= wm
    )


def _next_watermark(all_docs: Sequence[SourceDocument], wm: str | None) -> str | None:
    dates = [d.updated_at for d in all_docs if d.updated_at]
    if wm:
        dates.append(wm)
    return max(dates) if dates else wm


def _checkpointed_delta(
    checkpoint: ConnectorCheckpoint | None,
    all_docs: Sequence[SourceDocument],
    *,
    complete: bool,
) -> CheckpointedBatch:
    """Emit only documents newer than the prior watermark AND not already seen.

    Dual guard: the publish-date watermark is the primary delta; the seen-id belt
    catches feeds with missing or identical dates so a re-poll never re-emits an
    unchanged entry. ``>= wm`` (not ``>``) so a new entry sharing the watermark
    second is still emitted.
    """
    prior_ids = set(checkpoint.seen_ids) if checkpoint else set()
    wm = checkpoint.watermark if checkpoint else None
    fresh = [d for d in all_docs if _is_fresh(d, prior_ids, wm)]
    new_wm = _next_watermark(all_docs, wm) if complete else wm
    new_ids = sorted(prior_ids | {d.id for d in fresh})[-_SEEN_CAP:]
    cp = ConnectorCheckpoint(has_more=False, watermark=new_wm, seen_ids=new_ids)
    return CheckpointedBatch(documents=fresh, checkpoint=cp)
