"""Linear scan of the existing Link-header next relation grammar."""

from __future__ import annotations

import re
from collections.abc import Iterator

_REL_NEXT = re.compile(r'\brel="?next"?')


def _candidates(raw: str) -> Iterator[tuple[int, int, int]]:
    """Yield URL bounds and parameter starts in header order."""
    pos = 0
    while pos < len(raw):
        left = raw.find("<", pos)
        if left < 0:
            return
        right = raw.find(">", left + 1)
        if right < 0:
            return
        pos = right + 1
        end = pos
        while end < len(raw) and raw[end].isspace():
            end += 1
        if right > left + 1 and end < len(raw) and raw[end] == ";":
            yield left + 1, right, end + 1


def next_link(raw: str) -> str | None:
    """Return the first matching next target in linear time."""
    relations = iter(_REL_NEXT.finditer(raw))
    relation = next(relations, None)
    comma = -1
    for left, right, start in _candidates(raw):
        if start > comma:
            comma = raw.find(",", start)
            if comma < 0:
                comma = len(raw)
        while relation is not None and relation.start() < start:
            relation = next(relations, None)
        if relation is not None and relation.start() < comma:
            return raw[left:right]
    return None
