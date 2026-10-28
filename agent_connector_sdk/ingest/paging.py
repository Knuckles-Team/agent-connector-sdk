"""Cursor strategies: how a source's pages are walked and checkpointed.

A strategy turns the page just read into the next cursor, or ``None`` to stop.
:meth:`SourceStream.sync <agent_connector_sdk.ingest.stream.SourceStream.sync>`
commits each page with that cursor, so a later run resumes from it. Object
listings use :class:`KeysetCursor` on the key field (the listing marker).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from agent_connector_sdk.ingest.errors import IngestError

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


def _page_size(value: int) -> int:
    if type(value) is not int or value < 1:
        raise IngestError("page_size must be a positive integer")
    return value


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


@dataclass(frozen=True)
class KeysetCursor:
    """Key-set paging: the cursor is the ``key`` of the last record read.

    Fits primary-key paging and object listings whose marker is the last key.
    """

    key: str
    page_size: int

    def __post_init__(self) -> None:
        _page_size(self.page_size)

    def first(self) -> str | None:
        return None

    def advance(
        self, records: Sequence[Mapping[str, Any]], cursor: str | None
    ) -> str | None:
        if len(records) < self.page_size:
            return None
        last = records[-1].get(self.key)
        if last is None or last == "":
            raise IngestError(f"last record has no {self.key!r} to continue from")
        return str(last)


@dataclass(frozen=True)
class TimeWindowCursor:
    """Time-window paging: the cursor is the ISO start of the next window.

    Windows of ``window`` run from ``start`` to ``end`` (now when ``None``).
    An empty window still advances.
    """

    start: datetime
    window: timedelta
    end: datetime | None = None

    def __post_init__(self) -> None:
        if self.window <= timedelta(0):
            raise IngestError("window must be positive")

    def first(self) -> str | None:
        return self.start.isoformat()

    def advance(
        self, records: Sequence[Mapping[str, Any]], cursor: str | None
    ) -> str | None:
        current = datetime.fromisoformat(cursor) if cursor else self.start
        following = current + self.window
        limit = self.end or datetime.now(UTC)
        if following.tzinfo is None and limit.tzinfo is not None:
            limit = limit.replace(tzinfo=None)
        return None if following >= limit else following.isoformat()


@dataclass(frozen=True)
class HighWaterCursor:
    """High-water-mark paging: the cursor is the greatest ``key`` value read.

    The source returns only records newer than the cursor, so an incremental
    run reads changes since the last accepted mark. ``key`` values must sort
    as text (ISO timestamps or zero-padded revisions). A page with no records
    ends the walk.
    """

    key: str

    def first(self) -> str | None:
        return None

    def advance(
        self, records: Sequence[Mapping[str, Any]], cursor: str | None
    ) -> str | None:
        marks = [str(r[self.key]) for r in records if r.get(self.key) not in (None, "")]
        if not marks:
            return None
        return max([*marks, cursor] if cursor else marks)
