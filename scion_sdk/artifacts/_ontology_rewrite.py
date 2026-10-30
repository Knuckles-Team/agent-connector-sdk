"""Token-surgical removal of ``owl:imports`` objects from a lexed Turtle match."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from scion_sdk.artifacts._ontology_edits import (
    Edit,
    _apply_edits,
    _ImportSeparators,
    _plain_gap_edit,
    _punctuation_span,
    _span_edit,
)
from scion_sdk.artifacts._ontology_lexer import (
    _COMMA_RE,
    _IRI,
    _PREDICATE_RE,
    _SUBJECT_RE,
    _mask_turtle,
)


@dataclass(frozen=True)
class _Located:
    """A matched import predicate/object list inside the masked view."""

    match: re.Match[str]
    original: str
    masked: str
    predicate: re.Match[str]
    objects: tuple[re.Match[str], ...]


def _match_is_parsed_import(
    match: re.Match[str], parsed: frozenset[str] | None
) -> bool:
    """Reject a masked match absent from the parser's actual import triples."""
    if parsed is None:
        return True
    return set(_IRI.findall(match.group("objs"))).issubset(parsed)


def _locate(original: str, match: re.Match[str]) -> _Located | None:
    """Locate actual predicate/object tokens in a masked match.

    The regex match may contain comments between tokens.  Looking up spans in
    the masked view keeps comment examples and literal contents out of the
    object list while retaining their original offsets for surgical edits.
    """
    masked = _mask_turtle(original)
    predicate = _PREDICATE_RE.search(masked, match.start(), match.end())
    if predicate is None:
        return None
    object_start, object_end = match.span("objs")
    objects = tuple(_IRI.finditer(masked, object_start, object_end))
    if not objects:
        return None
    return _Located(match, original, masked, predicate, objects)


def _neighbour_edits(loc: _Located, seps: _ImportSeparators) -> list[Edit]:
    """Edits for the separators and subject that go with a removed predicate."""
    objects, masked, match = loc.objects, loc.masked, loc.match
    edits: list[Edit] = []
    if seps.preceding:
        bounds = (match.start(), loc.predicate.start())
        edits += _span_edit(_punctuation_span(masked, ";", bounds, reverse=True))
    if seps.following:
        bounds = (objects[-1].end(), match.end())
        edits += _span_edit(_punctuation_span(masked, ";", bounds))
    if seps.subject:
        subject = _SUBJECT_RE.search(masked, match.start(), loc.predicate.start())
        if subject is not None:
            edits.append((subject.start(), subject.end(), ""))
    if seps.terminator:
        bounds = (objects[-1].end(), match.end())
        edits += _span_edit(_punctuation_span(masked, ".", bounds))
    return edits


def _full_removal_tokens(loc: _Located, seps: _ImportSeparators) -> list[Edit]:
    """Edits deleting every object, comma, the predicate and chosen neighbours."""
    objects, masked = loc.objects, loc.masked
    edits: list[Edit] = [(o.start(), o.end(), "") for o in objects]
    edits.extend(
        (comma.start(), comma.end(), "")
        for comma in _COMMA_RE.finditer(masked, objects[0].end(), objects[-1].start())
    )
    edits.append((loc.predicate.start(), loc.predicate.end(), ""))
    return edits + _neighbour_edits(loc, seps)


def _end_boundary(loc: _Located, seps: _ImportSeparators) -> int:
    end = loc.match.end()
    if seps.terminator or not seps.preceding or seps.following:
        return end
    bounds = (loc.objects[-1].end(), end)
    terminator = _punctuation_span(loc.masked, ".", bounds)
    return end if terminator is None else terminator[0]


def _full_removal_edits(loc: _Located, seps: _ImportSeparators) -> list[Edit]:
    edits = _full_removal_tokens(loc, seps)
    token_spans = sorted((s, e) for s, e, _ in edits if s < e)
    if not token_spans:
        return edits
    boundary = _end_boundary(loc, seps)
    gaps = [
        _plain_gap_edit(loc.original, loc.match.start(), token_spans[0][0]),
        *(
            _plain_gap_edit(loc.original, previous[1], current[0])
            for previous, current in pairwise(token_spans)
        ),
        _plain_gap_edit(loc.original, token_spans[-1][1], boundary),
    ]
    return edits + [gap for gap in gaps if gap is not None]


def _removed_runs(removed: list[int]) -> list[tuple[int, int]]:
    """Maximal runs of consecutive removed object indices as (first, last)."""
    runs: list[tuple[int, int]] = []
    for index in removed:
        if runs and runs[-1][1] + 1 == index:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def _run_edits(loc: _Located, first: int, last: int) -> list[Edit]:
    objects, masked = loc.objects, loc.masked
    edits: list[Edit] = [
        (objects[index].start(), objects[index].end(), "")
        for index in range(first, last + 1)
    ]
    for index in range(first, last):
        between = (objects[index].end(), objects[index + 1].start())
        edits += _span_edit(_punctuation_span(masked, ",", between))
    if first > 0:
        between = (objects[first - 1].end(), objects[first].start())
        next_start = objects[first].start()
    elif last + 1 < len(objects):
        between = (objects[last].end(), objects[last + 1].start())
        next_start = objects[last + 1].start()
    else:
        return edits
    comma = _punctuation_span(masked, ",", between)
    if comma is None:
        return edits
    edits.append((*comma, ""))
    gap = _plain_gap_edit(loc.original, comma[1], next_start)
    return edits + ([gap] if gap is not None else [])


def _partial_removal_edits(loc: _Located, removed: list[int]) -> list[Edit]:
    edits: list[Edit] = []
    for first, last in _removed_runs(removed):
        edits += _run_edits(loc, first, last)
    return edits


def _rewrite_import_match(
    match: re.Match[str],
    original: str,
    *,
    keep: Callable[[str], bool],
    parsed: frozenset[str] | None,
    dropped: list[str],
    separators: _ImportSeparators | None = None,
) -> str:
    """Rewrite only actual import tokens, preserving comments and gaps."""
    unchanged = original[match.start() : match.end()]
    if not _match_is_parsed_import(match, parsed):
        return unchanged
    loc = _locate(original, match)
    if loc is None:
        return unchanged
    removed = [
        index
        for index, object_match in enumerate(loc.objects)
        if not keep(object_match.group(1))
    ]
    if not removed:
        return unchanged
    dropped.extend(loc.objects[index].group(1) for index in removed)
    if len(removed) == len(loc.objects):
        edits = _full_removal_edits(loc, separators or _ImportSeparators())
    else:
        edits = _partial_removal_edits(loc, removed)
    return _apply_edits(original, match, edits)
