"""Edit primitives for the ontology import rewriter."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

Edit = tuple[int, int, str]


@dataclass(frozen=True)
class _ImportSeparators:
    """Which neighbouring punctuation goes with a fully removed predicate."""

    preceding: bool = False
    following: bool = False
    subject: bool = False
    terminator: bool = False


def _apply_edits(
    text: str,
    match: re.Match[str],
    edits: Collection[Edit],
) -> str:
    """Apply token-span edits while retaining every unedited source byte."""
    start, end = match.span()
    chunks: list[str] = []
    cursor = start
    for edit_start, edit_end, replacement in sorted(edits):
        if edit_start < start or edit_end > end or edit_start < cursor:
            raise ValueError("overlapping or out-of-range Turtle token edit")
        chunks.append(text[cursor:edit_start])
        chunks.append(replacement)
        cursor = edit_end
    chunks.append(text[cursor:end])
    return "".join(chunks)


def _punctuation_span(
    masked: str, punctuation: str, bounds: tuple[int, int], *, reverse: bool = False
) -> tuple[int, int] | None:
    """Find punctuation visible in the masked lexical view."""
    start, end = bounds
    if reverse:
        position = masked.rfind(punctuation, start, end)
    else:
        position = masked.find(punctuation, start, end)
    if position < 0:
        return None
    return position, position + len(punctuation)


def _plain_gap_edit(text: str, start: int, end: int) -> Edit | None:
    """Drop a token gap only when it contains no comment bytes."""
    if start >= end or "#" in text[start:end]:
        return None
    return start, end, ""


def _span_edit(span: tuple[int, int] | None) -> list[Edit]:
    return [] if span is None else [(*span, "")]
