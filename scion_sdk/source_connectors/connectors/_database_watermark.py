"""Watermark ordering for the database document source."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from ..base import SourceDocument

_INTEGER_WATERMARK_RE = re.compile(r"[+-]?[0-9]+\Z")
_TIMESTAMP_WATERMARK_RE = re.compile(r"\d{4}-\d{2}-\d{2}[Tt ]")
_MAX_WATERMARK_CHARS = 256


def _require_bounded(candidate: str, previous: str, kind: str) -> None:
    if len(candidate) > _MAX_WATERMARK_CHARS or len(previous) > _MAX_WATERMARK_CHARS:
        raise ValueError(f"database {kind} watermark is too large")


def _timestamp_after(candidate: str, previous: str) -> bool:
    _require_bounded(candidate, previous, "timestamp")
    try:
        candidate_datetime = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        previous_datetime = datetime.fromisoformat(previous.replace("Z", "+00:00"))
        return candidate_datetime > previous_datetime
    except (TypeError, ValueError) as exc:
        raise ValueError("database timestamp watermarks are incomparable") from exc


def _watermark_after(candidate: str, previous: str) -> bool:
    """Compare integer and timestamp watermarks by value, and other text lexically."""
    candidate_integer = _INTEGER_WATERMARK_RE.fullmatch(candidate) is not None
    previous_integer = _INTEGER_WATERMARK_RE.fullmatch(previous) is not None
    if candidate_integer and previous_integer:
        _require_bounded(candidate, previous, "integer")
        return int(candidate) > int(previous)
    if candidate_integer != previous_integer:
        raise ValueError("database watermark types do not match")
    candidate_time = _TIMESTAMP_WATERMARK_RE.match(candidate) is not None
    previous_time = _TIMESTAMP_WATERMARK_RE.match(previous) is not None
    if candidate_time != previous_time:
        raise ValueError("database watermark types do not match")
    if candidate_time:
        return _timestamp_after(candidate, previous)
    return candidate > previous


def _newer_than(
    documents: Sequence[SourceDocument], prior: str
) -> list[SourceDocument]:
    """Keep documents with no timestamp or a timestamp after ``prior``."""
    return [
        doc
        for doc in documents
        if doc.updated_at is None or _watermark_after(doc.updated_at, prior)
    ]


def _max_watermark(
    documents: Sequence[SourceDocument], prior: str | None
) -> str | None:
    """Advance ``prior`` to the greatest ``updated_at`` among ``documents``."""
    highest = prior
    for doc in documents:
        if doc.updated_at is None:
            continue
        if highest is None:
            _watermark_after(doc.updated_at, doc.updated_at)
            highest = doc.updated_at
        elif _watermark_after(doc.updated_at, highest):
            highest = doc.updated_at
    return highest
