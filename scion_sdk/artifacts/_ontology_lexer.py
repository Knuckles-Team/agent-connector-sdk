"""Position-preserving Turtle lexing shared by the ontology import rewriters."""

from __future__ import annotations

import re

_OWL_IMPORTS_IRI = "http://www.w3.org/2002/07/owl#imports"
_PREDICATE = rf"(?:owl:imports|<{re.escape(_OWL_IMPORTS_IRI)}>)"
_PREDICATE_RE = re.compile(_PREDICATE)
_COMMA_RE = re.compile(",")
_SUBJECT_RE = re.compile(r"(?:<[^<>\s]*>|[A-Za-z0-9_.-]*:[A-Za-z0-9_.-]*)")
_IRI = re.compile(r"<([^<>\s]*)>")

_MASK = "\x00"


def _blank(text: str, masked: list[str], index: int) -> None:
    """Mask one character, keeping newlines so offsets and lines survive."""
    if text[index] != "\n":
        masked[index] = _MASK


def _mask_comment(text: str, masked: list[str], index: int) -> int:
    index += 1
    while index < len(text) and text[index] != "\n":
        masked[index] = " "
        index += 1
    return index


def _skip_iri(text: str, index: int) -> int:
    """Step past ``<...>``; IRIs (including ``#`` fragments) stay visible."""
    index += 1
    while index < len(text):
        if text[index] == ">":
            return index + 1
        index += 1
    return index


def _quote_delimiter(text: str, index: int) -> str | None:
    if text.startswith('"""', index) or text.startswith("'''", index):
        return text[index : index + 3]
    if text[index] in {'"', "'"}:
        return text[index]
    return None


def _mask_literal(text: str, masked: list[str], index: int, *, delimiter: str) -> int:
    width = len(delimiter)
    for offset in range(width):
        _blank(text, masked, index + offset)
    index += width
    while index < len(text):
        if text.startswith(delimiter, index):
            for offset in range(width):
                _blank(text, masked, index + offset)
            return index + width
        if text[index] == "\\" and index + 1 < len(text):
            masked[index] = _MASK
            _blank(text, masked, index + 1)
            index += 2
            continue
        _blank(text, masked, index)
        index += 1
    return index


def _scan(text: str, masked: list[str], index: int) -> int:
    char = text[index]
    if char == "#":
        return _mask_comment(text, masked, index)
    if char == "<":
        return _skip_iri(text, index)
    delimiter = _quote_delimiter(text, index)
    if delimiter is None:
        return index + 1
    return _mask_literal(text, masked, index, delimiter=delimiter)


def _mask_turtle(text: str) -> str:
    """Mask comments and quoted literals while preserving every character offset.

    Import matching is deliberately done against this lexed view.  A plain
    regular expression over the served bytes can mistake documentation in a
    comment or literal for an RDF predicate/object pair.  IRIs remain visible,
    including ``#`` fragments, because they are RDF terms rather than comments.
    """
    masked = list(text)
    index = 0
    while index < len(text):
        index = _scan(text, masked, index)
    return "".join(masked)
