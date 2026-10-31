"""Cursor strategies: how a source's pages are walked and checkpointed.

A strategy turns the page just read into the next cursor, or ``None`` to stop.
:meth:`SourceStream.sync <scion_sdk.ingest.stream.SourceStream.sync>`
commits each page with that cursor, so a later run resumes from it. Object
listings use :class:`KeysetCursor` on the key field (the listing marker).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from scion_sdk.ingest._paging_windows import (
    HighWaterCursor,
    KeysetCursor,
    TimeWindowCursor,
    _page_size,
)

__all__ = [
    "CursorStrategy",
    "HighWaterCursor",
    "KeysetCursor",
    "OffsetCursor",
    "TimeWindowCursor",
]


class CursorStrategy(Protocol):
    """How a paged source advances."""

    def first(self) -> str | None:
        """The cursor of the first page when the stream has no accepted cursor."""

    def advance(
        self, records: Sequence[Mapping[str, Any]], cursor: str | None
    ) -> str | None:
        """The cursor after ``records`` were read at ``cursor``; ``None`` ends the walk."""


@dataclass(frozen=True)
class OffsetCursor:
    """Offset paging: the cursor is the count of records already read."""

    page_size: int

    def __post_init__(self) -> None:
        _page_size(self.page_size)

    def first(self) -> str | None:
        return "0"

    def advance(
        self, records: Sequence[Mapping[str, Any]], cursor: str | None
    ) -> str | None:
        if len(records) < self.page_size:
            return None
        return str(int(cursor or 0) + len(records))
